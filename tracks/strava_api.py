from __future__ import annotations

import json
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape


STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


class StravaApiError(Exception):
    pass


def build_authorization_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    approval_prompt: str = "auto",
) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": approval_prompt,
            "scope": "read,activity:read_all,activity:write",
            "state": state,
        }
    )
    return f"{STRAVA_AUTH_URL}?{query}"


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    return _post_json(
        STRAVA_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
    )


def refresh_token(client_id: str, client_secret: str, refresh_token_value: str) -> dict:
    return _post_json(
        STRAVA_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token_value,
            "grant_type": "refresh_token",
        },
    )


def list_activities(access_token: str, page: int = 1, per_page: int = 30) -> list[dict]:
    query = urllib.parse.urlencode({"page": page, "per_page": per_page})
    return _get_json(f"{STRAVA_API_BASE}/athlete/activities?{query}", access_token)


def get_activity_detail(access_token: str, activity_id: str | int) -> dict:
    return _get_json(f"{STRAVA_API_BASE}/activities/{activity_id}", access_token)


def get_activity_streams(access_token: str, activity_id: str) -> dict:
    query = urllib.parse.urlencode(
        {
            "keys": "latlng,time,altitude",
            "key_by_type": "true",
        }
    )
    return _get_json(
        f"{STRAVA_API_BASE}/activities/{activity_id}/streams?{query}",
        access_token,
    )


def upload_gpx_activity(
    access_token: str,
    file_name: str,
    content: bytes,
    activity_name: str,
    activity_type: str,
    description: str,
) -> dict:
    boundary = f"----GPXEraser{uuid.uuid4().hex}"
    fields = {
        "name": activity_name,
        "description": description,
        "data_type": "gpx",
        "activity_type": activity_type,
    }
    body = _multipart_body(boundary, fields, file_name, content)
    request = urllib.request.Request(
        f"{STRAVA_API_BASE}/uploads",
        data=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    return _send_json_request(request)


def get_upload_status(access_token: str, upload_id: str | int) -> dict:
    return _get_json(f"{STRAVA_API_BASE}/uploads/{upload_id}", access_token)


def streams_to_gpx(activity: dict, streams: dict) -> bytes:
    latlng = streams.get("latlng", {}).get("data", [])
    times = streams.get("time", {}).get("data", [])
    altitudes = streams.get("altitude", {}).get("data", [])

    if not latlng:
        raise StravaApiError("У вибраній активності немає GPS-координат.")

    start_time = _parse_start_time(activity.get("start_date"))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="GPX Eraser" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <trk>",
        f"    <name>{escape(activity.get('name') or 'Strava activity')}</name>",
        "    <trkseg>",
    ]

    for index, coordinate in enumerate(latlng):
        if len(coordinate) != 2:
            continue
        lat, lon = coordinate
        lines.append(f'      <trkpt lat="{lat:.7f}" lon="{lon:.7f}">')
        if index < len(altitudes) and altitudes[index] is not None:
            lines.append(f"        <ele>{float(altitudes[index]):.1f}</ele>")
        if start_time and index < len(times):
            point_time = datetime.fromtimestamp(
                start_time.timestamp() + int(times[index]),
                tz=timezone.utc,
            )
            lines.append(f"        <time>{point_time.isoformat().replace('+00:00', 'Z')}</time>")
        lines.append("      </trkpt>")

    lines.extend(["    </trkseg>", "  </trk>", "</gpx>"])
    return "\n".join(lines).encode("utf-8")


def _parse_start_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _post_json(url: str, payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    return _send_json_request(request)


def _get_json(url: str, access_token: str) -> dict | list:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    return _send_json_request(request)


def _multipart_body(
    boundary: str,
    fields: dict[str, str],
    file_name: str,
    content: bytes,
) -> bytes:
    lines: list[bytes] = []
    for name, value in fields.items():
        lines.extend(
            [
                f"--{boundary}".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"'.encode("utf-8"),
                b"",
                value.encode("utf-8"),
            ]
        )

    lines.extend(
        [
            f"--{boundary}".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{file_name}"'.encode(
                "utf-8"
            ),
            b"Content-Type: application/gpx+xml",
            b"",
            content,
            f"--{boundary}--".encode("utf-8"),
            b"",
        ]
    )
    return b"\r\n".join(lines)


def _send_json_request(request: urllib.request.Request) -> dict | list:
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
            if not body:
                return {}
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StravaApiError(f"Strava API повернув помилку {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise StravaApiError(f"Не вдалося підключитися до Strava: {exc.reason}") from exc
