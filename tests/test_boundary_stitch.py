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


class SharedBoundaryTopologyTests(unittest.TestCase):
    def test_expected_shared_edge_snaps_to_smoothed_reference_not_raw_staircase(self):
        from api.services.boundary_stitch import align_expected_shared_boundary

        raw_left = Polygon([(0, 0), (100, 0), (100, 200), (0, 200), (0, 0)])
        raw_right = Polygon([(100, 0), (200, 0), (200, 200), (100, 200), (100, 0)])
        reference = Polygon([(103, 0), (200, 0), (200, 200), (103, 200), (103, 0)])
        moving = Polygon([(0, 0), (98, 0), (98, 200), (0, 200), (0, 0)])

        aligned, meta = align_expected_shared_boundary(
            moving,
            reference,
            raw_left,
            raw_right,
            snap_tolerance_m=10.0,
            raw_contact_tolerance_m=0.25,
        )

        self.assertTrue(meta["aligned"])
        shared = aligned.boundary.intersection(reference.boundary)
        self.assertGreater(shared.length, 190.0)
        self.assertLess(aligned.boundary.distance(LineString([(103, 0), (103, 200)])), 1e-9)

    def test_non_shared_raw_edges_are_not_snapped_even_when_display_edges_are_near(self):
        from api.services.boundary_stitch import align_expected_shared_boundary

        raw_left = Polygon([(0, 0), (80, 0), (80, 200), (0, 200), (0, 0)])
        raw_right = Polygon([(120, 0), (200, 0), (200, 200), (120, 200), (120, 0)])
        reference = Polygon([(103, 0), (200, 0), (200, 200), (103, 200), (103, 0)])
        moving = Polygon([(0, 0), (98, 0), (98, 200), (0, 200), (0, 0)])

        aligned, meta = align_expected_shared_boundary(
            moving,
            reference,
            raw_left,
            raw_right,
            snap_tolerance_m=10.0,
            raw_contact_tolerance_m=0.25,
        )

        self.assertFalse(meta["aligned"])
        self.assertAlmostEqual(aligned.area, moving.area)
        self.assertAlmostEqual(aligned.bounds[2], 98.0)

class SharedBoundaryArtifactRegressionTests(unittest.TestCase):
    def test_adjacent_shared_edge_replaces_hook_instead_of_boolean_growth(self):
        from api.services.boundary_stitch import align_expected_shared_boundary

        raw_lower = Polygon([(0, 0), (200, 0), (200, 100), (0, 100), (0, 0)])
        raw_upper = Polygon([(0, 100), (200, 100), (200, 200), (0, 200), (0, 100)])
        reference = Polygon([
            (0, 104), (50, 103), (100, 106), (150, 102), (200, 104),
            (200, 200), (0, 200), (0, 104),
        ])
        # Deliberate one-cell-ish hook/spike along the edge that should be shared.
        moving = Polygon([
            (0, 0), (200, 0), (200, 98), (150, 99), (151, 110),
            (145, 100), (100, 101), (50, 98), (0, 100), (0, 0),
        ])

        aligned, meta = align_expected_shared_boundary(
            moving, reference, raw_lower, raw_upper,
            snap_tolerance_m=20.0,
            raw_contact_tolerance_m=0.25,
            relationship="adjacent",
        )

        expected = Polygon([
            (0, 0), (200, 0), (200, 104), (150, 102), (100, 106),
            (50, 103), (0, 104), (0, 0),
        ])
        self.assertTrue(meta["aligned"])
        self.assertEqual(meta.get("method"), "shared_arc_replacement")
        self.assertTrue(aligned.is_valid)
        self.assertGreater(aligned.boundary.intersection(reference.boundary).length, 190.0)
        # The old buffer/union method left tens-to-hundreds of square metres of
        # hook-shaped detour. Arc replacement should be almost the canonical shape.
        self.assertLess(aligned.symmetric_difference(expected).area, 25.0)

    def test_same_flow_shared_edge_stays_smooth_and_nested(self):
        from api.services.boundary_stitch import align_expected_shared_boundary

        raw_upstream = Polygon([(0, 0), (150, 0), (150, 100), (0, 100), (0, 0)])
        raw_downstream = Polygon([(0, 0), (250, 0), (250, 200), (0, 200), (0, 0)])
        downstream = Polygon([
            (2, 3), (80, -2), (150, 4), (220, 1), (250, 10),
            (250, 200), (0, 200), (2, 3),
        ])
        upstream = Polygon([
            (-3, 2), (75, 1), (149, -4), (153, 13), (147, 8),
            (150, 100), (0, 100), (-3, 2),
        ])

        aligned, meta = align_expected_shared_boundary(
            upstream, downstream, raw_upstream, raw_downstream,
            snap_tolerance_m=20.0,
            raw_contact_tolerance_m=0.25,
            relationship="inside",
        )

        self.assertTrue(meta["aligned"])
        self.assertTrue(aligned.is_valid)
        self.assertLess(aligned.difference(downstream).area, 1e-6)
        self.assertGreater(aligned.boundary.intersection(downstream.boundary).length, 100.0)
