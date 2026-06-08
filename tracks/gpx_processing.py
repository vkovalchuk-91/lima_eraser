from __future__ import annotations

import math
import statistics
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable


ET.register_namespace("", "http://www.topografix.com/GPX/1/1")
ET.register_namespace("gpxtpx", "http://www.garmin.com/xmlschemas/TrackPointExtension/v1")
ET.register_namespace("gpxx", "http://www.garmin.com/xmlschemas/GpxExtensions/v3")
ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

MAX_REALISTIC_SPEED_MPS = 33.3  # 120 km/h, generous for cycling descents and GPS noise.
MIN_MOVING_SPEED_MPS = 0.5
DISPLAY_POINT_LIMIT = 3000
MAX_LOCAL_ANOMALY_POINTS = 240
MAX_LARGE_JUMP_ANOMALY_POINTS = 1000
MAX_LOCAL_ANOMALY_SECONDS = 300
MIN_LOCAL_DEVIATION_M = 80.0
MIN_LARGE_JUMP_DISTANCE_M = 1000.0


@dataclass(frozen=True)
class TrackPoint:
    index: int
    lat: float
    lon: float
    time: datetime | None
    element: ET.Element


def process_gpx(content: bytes) -> dict:
    root = ET.fromstring(content)
    namespace = _namespace(root)
    points = _extract_points(root, namespace)

    if len(points) < 2:
        cleaned_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return _result(points, points, cleaned_bytes, removed_count=0)

    keep_indexes = _find_clean_indexes(points)
    cleaned_points = [point for point in points if point.index in keep_indexes]
    _remove_points(root, namespace, keep_indexes)
    cleaned_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    return _result(
        original_points=points,
        cleaned_points=cleaned_points,
        cleaned_bytes=cleaned_bytes,
        removed_count=len(points) - len(cleaned_points),
    )


def shift_gpx_times(content: bytes, seconds: int) -> bytes:
    root = ET.fromstring(content)
    namespace = _namespace(root)
    delta = timedelta(seconds=seconds)

    for time_element in root.iter(_tag(namespace, "time")):
        parsed_time = _parse_time(time_element.text)
        if parsed_time is None:
            continue
        time_element.text = (parsed_time + delta).isoformat().replace("+00:00", "Z")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _namespace(root: ET.Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0][1:]
    return ""


def _tag(namespace: str, name: str) -> str:
    return f"{{{namespace}}}{name}" if namespace else name


def _extract_points(root: ET.Element, namespace: str) -> list[TrackPoint]:
    points: list[TrackPoint] = []
    for index, element in enumerate(root.iter(_tag(namespace, "trkpt"))):
        time_element = element.find(_tag(namespace, "time"))
        points.append(
            TrackPoint(
                index=index,
                lat=float(element.attrib["lat"]),
                lon=float(element.attrib["lon"]),
                time=_parse_time(time_element.text if time_element is not None else None),
                element=element,
            )
        )
    return points


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _find_clean_indexes(points: list[TrackPoint]) -> set[int]:
    geographically_plausible = _filter_to_main_geographic_cluster(points)
    candidates = [point for point in points if point.index in geographically_plausible]
    speed_plausible = _remove_speed_spikes(candidates)
    candidates = [point for point in candidates if point.index in speed_plausible]
    route_plausible = _remove_local_route_deviations(candidates)
    return geographically_plausible & speed_plausible & route_plausible


def _filter_to_main_geographic_cluster(points: list[TrackPoint]) -> set[int]:
    median_lat = statistics.median(point.lat for point in points)
    median_lon = statistics.median(point.lon for point in points)
    center = (median_lat, median_lon)
    distances = [_haversine(center, (point.lat, point.lon)) for point in points]

    if len(distances) < 4:
        return {point.index for point in points}

    sorted_distances = sorted(distances)
    q1 = _percentile(sorted_distances, 0.25)
    q3 = _percentile(sorted_distances, 0.75)
    iqr = max(q3 - q1, 1.0)
    threshold = max(50_000.0, q3 + (6 * iqr))

    return {
        point.index
        for point, distance_from_center in zip(points, distances)
        if distance_from_center <= threshold
    }


def _remove_speed_spikes(points: list[TrackPoint]) -> set[int]:
    if len(points) < 3:
        return {point.index for point in points}

    keep = {point.index for point in points}
    for previous, current, following in zip(points, points[1:], points[2:]):
        speed_in = _speed(previous, current)
        speed_out = _speed(current, following)
        speed_without_current = _speed(previous, following)

        if (
            speed_in is not None
            and speed_out is not None
            and speed_without_current is not None
            and speed_in > MAX_REALISTIC_SPEED_MPS
            and speed_out > MAX_REALISTIC_SPEED_MPS
            and speed_without_current <= MAX_REALISTIC_SPEED_MPS
        ):
            keep.discard(current.index)

    return keep


def _remove_local_route_deviations(points: list[TrackPoint]) -> set[int]:
    if len(points) < 4:
        return {point.index for point in points}

    keep = {point.index for point in points}
    local_threshold = _local_deviation_threshold(points)
    edge_distances = [
        _haversine((previous.lat, previous.lon), (current.lat, current.lon))
        for previous, current in zip(points, points[1:])
    ]
    bad_edges = [
        _is_bad_edge(previous, current, distance, local_threshold)
        for previous, current, distance in zip(points, points[1:], edge_distances)
    ]
    _discard_deviation_ranges(
        points=points,
        keep=keep,
        candidate_edges=bad_edges,
        local_threshold=local_threshold,
        max_anomaly_points=MAX_LOCAL_ANOMALY_POINTS,
    )

    large_jump_threshold = max(MIN_LARGE_JUMP_DISTANCE_M, local_threshold * 8)
    large_jump_edges = [distance >= large_jump_threshold for distance in edge_distances]
    _discard_deviation_ranges(
        points=points,
        keep=keep,
        candidate_edges=large_jump_edges,
        local_threshold=local_threshold,
        max_anomaly_points=MAX_LARGE_JUMP_ANOMALY_POINTS,
    )

    return keep


def _discard_deviation_ranges(
    points: list[TrackPoint],
    keep: set[int],
    candidate_edges: list[bool],
    local_threshold: float,
    max_anomaly_points: int,
) -> None:
    start_edge = 0
    while start_edge < len(candidate_edges):
        if not candidate_edges[start_edge]:
            start_edge += 1
            continue

        end_edge = _matching_return_edge(
            points=points,
            candidate_edges=candidate_edges,
            start_edge=start_edge,
            local_threshold=local_threshold,
            max_anomaly_points=max_anomaly_points,
        )
        if end_edge is None:
            start_edge += 1
            continue

        for point in points[start_edge + 1 : end_edge + 1]:
            keep.discard(point.index)
        start_edge = end_edge + 1


def _matching_return_edge(
    points: list[TrackPoint],
    candidate_edges: list[bool],
    start_edge: int,
    local_threshold: float,
    max_anomaly_points: int,
) -> int | None:
    max_end_edge = min(len(candidate_edges) - 1, start_edge + max_anomaly_points)

    for end_edge in range(start_edge + 1, max_end_edge + 1):
        if not candidate_edges[end_edge]:
            continue

        start_anchor = points[start_edge]
        end_anchor = points[end_edge + 1]
        if not _time_window_is_local(start_anchor, end_anchor):
            break
        if not _skip_between_anchors_is_plausible(start_anchor, end_anchor):
            continue
        if not _interior_points_deviate(points[start_edge : end_edge + 2], local_threshold):
            continue
        return end_edge

    return None


def _time_window_is_local(start: TrackPoint, end: TrackPoint) -> bool:
    seconds = _seconds_between(start, end)
    return seconds is None or seconds <= MAX_LOCAL_ANOMALY_SECONDS


def _skip_between_anchors_is_plausible(start: TrackPoint, end: TrackPoint) -> bool:
    speed = _speed(start, end)
    return speed is None or speed <= MAX_REALISTIC_SPEED_MPS


def _interior_points_deviate(points: list[TrackPoint], local_threshold: float) -> bool:
    if len(points) < 4:
        return False

    start = points[0]
    end = points[-1]
    direct_distance = _haversine((start.lat, start.lon), (end.lat, end.lon))
    path_distance = sum(
        _haversine((previous.lat, previous.lon), (current.lat, current.lon))
        for previous, current in zip(points, points[1:])
    )
    max_lateral_distance = max(
        _distance_to_segment_m(point, start, end) for point in points[1:-1]
    )

    return (
        max_lateral_distance >= local_threshold
        and path_distance >= direct_distance + (2 * local_threshold)
    )


def _is_bad_edge(
    previous: TrackPoint,
    current: TrackPoint,
    distance: float,
    local_threshold: float,
) -> bool:
    speed = _speed(previous, current)
    if speed is not None:
        return speed > MAX_REALISTIC_SPEED_MPS and distance >= local_threshold
    return distance >= max(250.0, local_threshold * 2)


def _local_deviation_threshold(points: list[TrackPoint]) -> float:
    segment_distances = sorted(
        _haversine((previous.lat, previous.lon), (current.lat, current.lon))
        for previous, current in zip(points, points[1:])
    )
    short_segments = [distance for distance in segment_distances if distance <= 250]
    reference = statistics.median(short_segments or segment_distances or [MIN_LOCAL_DEVIATION_M])
    return max(MIN_LOCAL_DEVIATION_M, reference * 12)


def _distance_to_segment_m(point: TrackPoint, start: TrackPoint, end: TrackPoint) -> float:
    origin_lat = math.radians(start.lat)
    meters_per_lat = 111_320.0
    meters_per_lon = 111_320.0 * math.cos(origin_lat)

    px = (point.lon - start.lon) * meters_per_lon
    py = (point.lat - start.lat) * meters_per_lat
    ex = (end.lon - start.lon) * meters_per_lon
    ey = (end.lat - start.lat) * meters_per_lat
    segment_length_sq = (ex * ex) + (ey * ey)

    if segment_length_sq == 0:
        return math.hypot(px, py)

    t = max(0.0, min(1.0, ((px * ex) + (py * ey)) / segment_length_sq))
    closest_x = t * ex
    closest_y = t * ey
    return math.hypot(px - closest_x, py - closest_y)


def _remove_points(root: ET.Element, namespace: str, keep_indexes: set[int]) -> None:
    current_index = 0
    for segment in root.iter(_tag(namespace, "trkseg")):
        for child in list(segment):
            if child.tag != _tag(namespace, "trkpt"):
                continue
            if current_index not in keep_indexes:
                segment.remove(child)
            current_index += 1


def _result(
    original_points: list[TrackPoint],
    cleaned_points: list[TrackPoint],
    cleaned_bytes: bytes,
    removed_count: int,
) -> dict:
    return {
        "original": {
            "metrics": _metrics(original_points),
            "coordinates": _coordinates_for_display(original_points),
        },
        "cleaned": {
            "metrics": _metrics(cleaned_points),
            "coordinates": _coordinates_for_display(cleaned_points),
        },
        "cleaned_bytes": cleaned_bytes,
        "removed_count": removed_count,
        "original_count": len(original_points),
        "cleaned_count": len(cleaned_points),
    }


def _metrics(points: list[TrackPoint]) -> dict:
    distance_m = 0.0
    moving_seconds = 0.0

    for previous, current in zip(points, points[1:]):
        segment_distance = _haversine((previous.lat, previous.lon), (current.lat, current.lon))
        distance_m += segment_distance
        seconds = _seconds_between(previous, current)
        if seconds and segment_distance / seconds >= MIN_MOVING_SPEED_MPS:
            moving_seconds += seconds

    average_speed_kmh = (distance_m / moving_seconds * 3.6) if moving_seconds else 0.0
    return {
        "distance_km": round(distance_m / 1000, 2),
        "average_speed_kmh": round(average_speed_kmh, 1),
        "moving_time": _format_duration(moving_seconds),
    }


def _coordinates_for_display(points: list[TrackPoint]) -> list[list[float]]:
    display_points = list(_downsample(points, DISPLAY_POINT_LIMIT))
    return [[point.lat, point.lon] for point in display_points]


def _downsample(points: list[TrackPoint], limit: int) -> Iterable[TrackPoint]:
    if len(points) <= limit:
        return points
    step = len(points) / limit
    return (points[min(int(index * step), len(points) - 1)] for index in range(limit))


def _speed(previous: TrackPoint, current: TrackPoint) -> float | None:
    seconds = _seconds_between(previous, current)
    if not seconds:
        return None
    return _haversine((previous.lat, previous.lon), (current.lat, current.lon)) / seconds


def _seconds_between(previous: TrackPoint, current: TrackPoint) -> float | None:
    if not previous.time or not current.time:
        return None
    seconds = (current.time - previous.time).total_seconds()
    return seconds if seconds > 0 else None


def _haversine(start: tuple[float, float], end: tuple[float, float]) -> float:
    lat1, lon1 = start
    lat2, lon2 = end
    radius_m = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = (len(sorted_values) - 1) * fraction
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
