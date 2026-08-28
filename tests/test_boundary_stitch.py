from __future__ import annotations

import unittest

from shapely.geometry import LineString, Polygon

from api.services.boundary_stitch import _best_official_arc


class BoundaryStitchTests(unittest.TestCase):
    def test_short_promoted_contact_gap_does_not_reject_exact_arc(self):
        """Validation must accept the same near-boundary allowance as classification."""
        official = Polygon([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])
        # The 204 m excursion is inside the 120 m run-classification allowance
        # (1.6 * 120 m + 30 m sample step), but outside the old 195 m arc guard.
        raw_segment = LineString([(0, 0), (500, 204), (1000, 0)])

        match = _best_official_arc(raw_segment, official, 120.0, 30.0)

        self.assertIsNotNone(match)
        self.assertAlmostEqual(match["arc"].length, 1000.0)


if __name__ == "__main__":
    unittest.main()
