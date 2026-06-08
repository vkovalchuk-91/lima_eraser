from django.test import SimpleTestCase

from .gpx_processing import process_gpx


class GpxProcessingTests(SimpleTestCase):
    def test_removes_large_jump_excursion_without_timestamps(self):
        normal_start = [
            (50.000000, 30.000000),
            (50.000200, 30.000300),
            (50.000400, 30.000600),
            (50.000600, 30.000900),
        ]
        anomalous_points = [
            (50.200000 + (index * 0.00001), 30.200000 + (index * 0.00001))
            for index in range(350)
        ]
        normal_end = [
            (50.000800, 30.001200),
            (50.001000, 30.001500),
        ]

        result = process_gpx(_gpx_from_points([*normal_start, *anomalous_points, *normal_end]))

        self.assertEqual(result["original_count"], 356)
        self.assertEqual(result["cleaned_count"], 6)
        self.assertEqual(result["removed_count"], 350)
        self.assertLess(result["cleaned"]["metrics"]["distance_km"], 1)


def _gpx_from_points(points: list[tuple[float, float]]) -> bytes:
    track_points = "\n".join(
        f'    <trkpt lat="{lat:.6f}" lon="{lon:.6f}"><ele>0</ele></trkpt>'
        for lat, lon in points
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
{track_points}
    </trkseg>
  </trk>
</gpx>
""".encode()
