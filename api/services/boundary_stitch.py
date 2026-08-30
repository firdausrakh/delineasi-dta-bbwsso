from __future__ import annotations

"""
Boundary reconstruction for DTA delineation.

The authoritative DAS boundary is treated as immutable geometry. FABDEM-derived
internal boundaries are smoothed with a PAEK-like local polynomial smoother
(exponential kernel) and then simplified with a Visvalingam-Whyatt effective-area
algorithm. Only the FABDEM portion is processed; official arcs are copied exactly.
"""

from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Iterable

import numpy as np
from shapely import distance as geometry_distance
from shapely import linestrings as geometry_linestrings
from shapely import make_valid, points as geometry_points, union_all
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring
from shapely.strtree import STRtree


@dataclass
class StitchDiagnostics:
    # PAEK/VW are supplied by the caller. Their application defaults live only
    # in api/core.py so this service never owns a second configuration source.
    paek_tolerance_m: float
    vw_tolerance_m: float
    mode: str = "fabdem_processed"
    method: str = "no_official_match"
    match_tolerance_m: float = 90.0
    smoothing_method: str = "PAEK-like exponential-kernel local quadratic"
    simplification_method: str = "Visvalingam-Whyatt effective-area"
    matched_raw_boundary_length_m: float = 0.0
    official_boundary_length_m: float = 0.0
    internal_boundary_length_m: float = 0.0
    official_boundary_percent: float = 0.0
    raw_match_percent: float = 0.0
    final_official_5m_percent: float = 0.0
    final_official_tolerance_percent: float = 0.0
    official_segment_count: int = 0
    rejected_segment_count: int = 0
    internal_segment_count: int = 0
    area_adjustment_m2: float = 0.0
    raw_component_count: int = 1
    final_component_count: int = 1
    raw_vertex_count: int = 0
    final_vertex_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "method": self.method,
            "match_tolerance_m": float(self.match_tolerance_m),
            "paek_tolerance_m": float(self.paek_tolerance_m),
            "vw_tolerance_m": float(self.vw_tolerance_m),
            "smoothing_method": self.smoothing_method,
            "simplification_method": self.simplification_method,
            "matched_raw_boundary_length_m": float(self.matched_raw_boundary_length_m),
            "official_boundary_length_m": float(self.official_boundary_length_m),
            "internal_boundary_length_m": float(self.internal_boundary_length_m),
            "official_boundary_percent": float(self.official_boundary_percent),
            "raw_match_percent": float(self.raw_match_percent),
            "final_official_5m_percent": float(self.final_official_5m_percent),
            "final_official_tolerance_percent": float(self.final_official_tolerance_percent),
            "official_segment_count": int(self.official_segment_count),
            "rejected_segment_count": int(self.rejected_segment_count),
            "internal_segment_count": int(self.internal_segment_count),
            "area_adjustment_m2": float(self.area_adjustment_m2),
            "raw_component_count": int(self.raw_component_count),
            "final_component_count": int(self.final_component_count),
            "raw_vertex_count": int(self.raw_vertex_count),
            "final_vertex_count": int(self.final_vertex_count),
            "warnings": list(self.warnings),
        }


def _polygon_parts(geom) -> list[Polygon]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    if geom.geom_type == "GeometryCollection":
        return [g for g in geom.geoms if g.geom_type == "Polygon"]
    return []


def _line_parts(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type in ("LineString", "LinearRing"):
        return [LineString(geom.coords)]
    if geom.geom_type in ("MultiLineString", "GeometryCollection"):
        out: list[LineString] = []
        for part in geom.geoms:
            out.extend(_line_parts(part))
        return out
    return []


def _component_count(geom) -> int:
    return len(_polygon_parts(geom))


def _vertex_count(geom) -> int:
    count = 0
    for p in _polygon_parts(geom):
        count += len(p.exterior.coords)
        count += sum(len(r.coords) for r in p.interiors)
    if count:
        return count
    for line in _line_parts(geom):
        count += len(line.coords)
    return count


def _cumulative_distance(coords: np.ndarray) -> np.ndarray:
    if len(coords) <= 1:
        return np.array([0.0], dtype=float)
    diffs = np.diff(coords, axis=0)
    seg = np.hypot(diffs[:, 0], diffs[:, 1])
    return np.concatenate(([0.0], np.cumsum(seg)))


def _weighted_local_quadratic(u: np.ndarray, values: np.ndarray, weights: np.ndarray) -> float:
    """Value at u=0 of a weighted local quadratic; stable fallbacks for short windows."""
    if len(values) == 0:
        return float("nan")
    if len(values) < 3 or np.ptp(u) < 1e-9:
        total = float(np.sum(weights))
        return float(np.sum(values * weights) / total) if total > 0 else float(values[len(values) // 2])
    # Centered coordinates keep the tiny 3x3 least-squares problem well conditioned.
    A = np.column_stack((np.ones_like(u), u, u * u))
    sw = np.sqrt(np.maximum(weights, 1e-12))
    try:
        coeff, *_ = np.linalg.lstsq(A * sw[:, None], values * sw, rcond=None)
        return float(coeff[0])
    except np.linalg.LinAlgError:
        total = float(np.sum(weights))
        return float(np.sum(values * weights) / total) if total > 0 else float(values[len(values) // 2])


def _paek_smooth_line(line: LineString, tolerance_m: float, *, closed: bool = False) -> LineString:
    """
    PAEK-like smoothing.

    ArcGIS PAEK uses a polynomial approximation with an exponential kernel along
    the line. This implementation follows that principle using a local quadratic
    regression over curvilinear distance and an exponential kernel. The tolerance
    controls the kernel bandwidth in projected metres.
    """
    coords_list = list(line.coords)
    if tolerance_m <= 0 or len(coords_list) < 4:
        return LineString(coords_list)

    if closed and coords_list[0] == coords_list[-1]:
        coords_list = coords_list[:-1]
    coords = np.asarray(coords_list, dtype=float)
    if len(coords) < (3 if closed else 4):
        out = coords.tolist()
        if closed and out and out[0] != out[-1]:
            out.append(out[0])
        return LineString(out)

    if closed:
        # Parameterize a circular ring without changing its source vertices.
        closed_coords = np.vstack((coords, coords[0]))
        s_closed = _cumulative_distance(closed_coords)
        total_len = float(s_closed[-1])
        if total_len <= 1e-9:
            return LineString(list(line.coords))
        s = s_closed[:-1]
        s_ext = np.concatenate((s - total_len, s, s + total_len))
        c_ext = np.vstack((coords, coords, coords))
        target_indices = range(len(coords))
    else:
        s = _cumulative_distance(coords)
        if float(s[-1]) <= 1e-9:
            return LineString(coords.tolist())
        s_ext = s
        c_ext = coords
        target_indices = range(len(coords))

    radius = max(float(tolerance_m) * 3.0, float(tolerance_m) + 1.0)
    out = np.empty_like(coords)
    for i in target_indices:
        si = float(s[i])
        lo = int(np.searchsorted(s_ext, si - radius, side="left"))
        hi = int(np.searchsorted(s_ext, si + radius, side="right"))
        local_s = s_ext[lo:hi]
        local_c = c_ext[lo:hi]
        if len(local_s) < 3:
            out[i] = coords[i]
            continue
        u = local_s - si
        # Exponential kernel: points farther than tolerance still contribute,
        # but rapidly lose influence; the 3*tolerance window bounds cost.
        weights = np.exp(-np.square(np.abs(u) / max(float(tolerance_m), 1e-9)))
        out[i, 0] = _weighted_local_quadratic(u, local_c[:, 0], weights)
        out[i, 1] = _weighted_local_quadratic(u, local_c[:, 1], weights)

    if not closed:
        # Internal chains must meet the later snapping/stitching step predictably.
        out[0] = coords[0]
        out[-1] = coords[-1]
        return LineString(out.tolist())

    result = out.tolist()
    result.append(result[0])
    return LineString(result)


def _triangle_effective_height(a, b, c) -> float:
    """VW effective area expressed as triangle height in layer units (metres)."""
    base = float(np.hypot(c[0] - a[0], c[1] - a[1]))
    if base <= 1e-12:
        return 0.0
    twice_area = abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))
    return float(twice_area / base)


def _vw_simplify_line(line: LineString, tolerance_m: float, *, closed: bool = False) -> LineString:
    """
    Visvalingam-Whyatt effective-area simplification.

    The user-facing tolerance is expressed in projected metres. Internally the
    effective triangle area is normalized to its equivalent perpendicular height,
    which keeps the user-facing tolerance intuitive and consistent with GIS distance units.
    """
    coords = list(line.coords)
    if tolerance_m <= 0 or len(coords) < 4:
        return LineString(coords)

    if closed and coords[0] == coords[-1]:
        coords = coords[:-1]
    n = len(coords)
    min_vertices = 3 if closed else 2
    if n <= min_vertices:
        out = coords[:]
        if closed and out:
            out.append(out[0])
        return LineString(out)

    prev = [i - 1 for i in range(n)]
    nxt = [i + 1 for i in range(n)]
    alive = [True] * n
    version = [0] * n
    if closed:
        prev[0] = n - 1
        nxt[-1] = 0
    else:
        prev[0] = -1
        nxt[-1] = -1

    def score(i: int) -> float:
        if not alive[i]:
            return float("inf")
        pi, ni = prev[i], nxt[i]
        if pi < 0 or ni < 0:
            return float("inf")
        return _triangle_effective_height(coords[pi], coords[i], coords[ni])

    heap: list[tuple[float, int, int]] = []
    for i in range(n):
        heappush(heap, (score(i), i, version[i]))

    remaining = n
    while heap and remaining > min_vertices:
        sc, i, ver = heappop(heap)
        if not alive[i] or ver != version[i]:
            continue
        current = score(i)
        if abs(current - sc) > 1e-9:
            version[i] += 1
            heappush(heap, (current, i, version[i]))
            continue
        if current >= tolerance_m:
            break
        pi, ni = prev[i], nxt[i]
        if pi < 0 or ni < 0:
            continue
        alive[i] = False
        remaining -= 1
        nxt[pi] = ni
        prev[ni] = pi
        for j in (pi, ni):
            if j >= 0 and alive[j]:
                version[j] += 1
                heappush(heap, (score(j), j, version[j]))

    kept = [coords[i] for i in range(n) if alive[i]]
    if not closed:
        if kept[0] != coords[0]:
            kept.insert(0, coords[0])
        if kept[-1] != coords[-1]:
            kept.append(coords[-1])
        return LineString(kept)

    if len(kept) < 3:
        return LineString(list(line.coords))
    kept.append(kept[0])
    return LineString(kept)


def process_fabdem_line(
    line: LineString,
    *,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
    closed: bool = False,
) -> LineString:
    smoothed = _paek_smooth_line(line, paek_tolerance_m, closed=closed)
    simplified = _vw_simplify_line(smoothed, vw_tolerance_m, closed=closed)
    return simplified


def process_fabdem_polygon(
    geom,
    *,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
):
    """PAEK-like smooth + VW simplify FABDEM-derived polygons only."""
    processed: list[Polygon] = []
    for poly in _polygon_parts(geom):
        ext = process_fabdem_line(
            LineString(poly.exterior.coords),
            paek_tolerance_m=paek_tolerance_m,
            vw_tolerance_m=vw_tolerance_m,
            closed=True,
        )
        holes: list[list[tuple[float, float]]] = []
        for ring in poly.interiors:
            processed_ring = process_fabdem_line(
                LineString(ring.coords),
                paek_tolerance_m=paek_tolerance_m,
                vw_tolerance_m=vw_tolerance_m,
                closed=True,
            )
            if len(processed_ring.coords) >= 4:
                holes.append(list(processed_ring.coords))
        candidate = Polygon(list(ext.coords), holes)
        if not candidate.is_valid:
            candidate = make_valid(candidate)
        processed.extend(_polygon_parts(candidate))
    if not processed:
        return geom
    result = union_all(processed)
    return make_valid(result) if not result.is_valid else result




def _sampled_arc_distance_score(arc: LineString, target: LineString) -> tuple[float, float, float]:
    """Score a closed-ring arc against the RAW shared edge.

    The topology repair only needs to identify which of the two possible ring arcs is
    the shared one.  Sampling by curvilinear distance avoids a bias toward dense RAW
    raster vertices and keeps this cheap for long catchment boundaries.
    """
    if arc is None or arc.is_empty or target is None or target.is_empty:
        return (float("inf"), float("inf"), float("inf"))
    count = max(3, min(128, int(np.ceil(float(arc.length) / 30.0)) + 1))
    distances = [arc.interpolate(float(d)).distance(target) for d in np.linspace(0.0, float(arc.length), count)]
    max_dist = float(max(distances, default=float("inf")))
    mean_dist = float(np.mean(distances)) if distances else float("inf")
    ratio = float(arc.length) / max(float(target.length), 1.0)
    length_penalty = abs(float(np.log(max(ratio, 1e-9))))
    return (mean_dist + max_dist * 0.25 + length_penalty * 8.0, max_dist, mean_dist)


def _ring_arc_pair(ring: LineString, raw_line: LineString):
    """Return (shared_arc start->end, complementary_arc end->start, score meta)."""
    if ring is None or ring.is_empty or raw_line is None or raw_line.is_empty:
        return None
    raw_coords = list(raw_line.coords)
    if len(raw_coords) < 2:
        return None
    start_pt = Point(raw_coords[0]); end_pt = Point(raw_coords[-1])
    da = float(ring.project(start_pt)); db = float(ring.project(end_pt))

    forward = _forward_arc(ring, da, db)
    backward_forward = _forward_arc(ring, db, da)
    reverse_route = _reverse(backward_forward)  # start -> end

    score_forward = _sampled_arc_distance_score(forward, raw_line)
    score_reverse = _sampled_arc_distance_score(reverse_route, raw_line)
    if score_forward[0] <= score_reverse[0]:
        return forward, backward_forward, {
            "score": score_forward[0], "max_distance_m": score_forward[1], "mean_distance_m": score_forward[2],
        }
    return reverse_route, _reverse(forward), {
        "score": score_reverse[0], "max_distance_m": score_reverse[1], "mean_distance_m": score_reverse[2],
    }


def _blend_complement_to_reference(
    complement: LineString,
    target_start: tuple[float, float],
    target_end: tuple[float, float],
    transition_m: float,
) -> LineString:
    """Move only the two ends of the non-shared arc toward the canonical junctions.

    Old boolean buffer/growth reconciliation left short perpendicular connectors at
    the ends of a shared edge (the visible 'hook' / staircase artifacts).  A smooth
    endpoint blend removes those connectors while keeping the rest of the already
    smoothed PAEK/VW boundary untouched.
    """
    if complement is None or complement.is_empty or complement.length <= 1e-6:
        return complement
    total = float(complement.length)
    transition = min(max(10.0, float(transition_m)), total * 0.24)
    if transition <= 1e-6:
        return complement

    original_start = complement.interpolate(0.0)
    original_end = complement.interpolate(total)
    ds = np.array([float(target_start[0]) - original_start.x, float(target_start[1]) - original_start.y])
    de = np.array([float(target_end[0]) - original_end.x, float(target_end[1]) - original_end.y])

    sample_count = max(5, min(18, int(np.ceil(transition / 12.0)) + 2))
    start_distances = np.linspace(0.0, transition, sample_count)
    end_distances = np.linspace(total - transition, total, sample_count)

    def smooth_weight(u: float) -> float:
        # 1 -> 0 with zero derivative at both ends (reverse smoothstep).
        u = max(0.0, min(1.0, float(u)))
        return 1.0 - (3.0 * u * u - 2.0 * u * u * u)

    start_coords: list[tuple[float, float]] = []
    for d in start_distances:
        p = complement.interpolate(float(d)); w = smooth_weight(float(d) / transition)
        start_coords.append((float(p.x + ds[0] * w), float(p.y + ds[1] * w)))
    start_coords[0] = (float(target_start[0]), float(target_start[1]))

    middle = substring(complement, transition, total - transition) if total > transition * 2.0 else None
    middle_coords = list(middle.coords) if middle is not None and not middle.is_empty else []

    end_coords: list[tuple[float, float]] = []
    for d in end_distances:
        p = complement.interpolate(float(d)); remaining = (total - float(d)) / transition
        w = smooth_weight(remaining)
        end_coords.append((float(p.x + de[0] * w), float(p.y + de[1] * w)))
    end_coords[-1] = (float(target_end[0]), float(target_end[1]))

    coords = _coords_join([
        LineString(start_coords),
        LineString(middle_coords) if len(middle_coords) >= 2 else LineString(),
        LineString(end_coords),
    ])
    if len(coords) < 2:
        return complement
    return LineString(coords)


def _replace_shared_exterior_arc(moving, reference, raw_line: LineString, tolerance_m: float):
    """Replace only the proven RAW-shared exterior arc with the reference smooth arc."""
    if not isinstance(moving, Polygon) or not isinstance(reference, Polygon):
        return moving, {"replaced": False, "reason": "non_polygon"}
    moving_ring = LineString(moving.exterior.coords)
    reference_ring = LineString(reference.exterior.coords)
    moving_pair = _ring_arc_pair(moving_ring, raw_line)
    reference_pair = _ring_arc_pair(reference_ring, raw_line)
    if moving_pair is None or reference_pair is None:
        return moving, {"replaced": False, "reason": "arc_not_found"}

    _, moving_complement, moving_meta = moving_pair
    reference_shared, _, reference_meta = reference_pair
    # PAEK=150 m can legitimately move an edge farther than the final topological
    # snap tolerance.  Still reject obviously unrelated arcs before surgery.
    max_arc_distance = max(float(tolerance_m) * 3.0, 120.0)
    if moving_meta["max_distance_m"] > max_arc_distance or reference_meta["max_distance_m"] > max_arc_distance:
        return moving, {
            "replaced": False, "reason": "arc_too_far",
            "moving_max_distance_m": moving_meta["max_distance_m"],
            "reference_max_distance_m": reference_meta["max_distance_m"],
        }

    ref_coords = list(reference_shared.coords)
    if len(ref_coords) < 2:
        return moving, {"replaced": False, "reason": "empty_reference_arc"}
    transition_m = max(float(tolerance_m) * 2.5, 60.0)
    blended = _blend_complement_to_reference(
        moving_complement,
        (float(ref_coords[-1][0]), float(ref_coords[-1][1])),
        (float(ref_coords[0][0]), float(ref_coords[0][1])),
        transition_m,
    )
    if blended is None or blended.is_empty:
        return moving, {"replaced": False, "reason": "blend_failed"}

    ring_coords = _coords_join([reference_shared, blended])
    if len(ring_coords) < 4:
        return moving, {"replaced": False, "reason": "short_ring"}
    if ring_coords[0] != ring_coords[-1]:
        ring_coords.append(ring_coords[0])
    holes = [list(ring.coords) for ring in moving.interiors]
    candidate = Polygon(ring_coords, holes)
    if not candidate.is_valid:
        candidate = make_valid(candidate)
    parts = _polygon_parts(candidate)
    if not parts:
        return moving, {"replaced": False, "reason": "invalid_candidate"}
    candidate = max(parts, key=lambda g: g.area)
    if candidate.is_empty:
        return moving, {"replaced": False, "reason": "empty_candidate"}
    return candidate, {
        "replaced": True,
        "shared_reference_length_m": float(reference_shared.length),
        "transition_m": transition_m,
        "moving_max_distance_m": moving_meta["max_distance_m"],
        "reference_max_distance_m": reference_meta["max_distance_m"],
    }


def align_expected_shared_boundary(
    moving,
    reference,
    raw_moving,
    raw_reference,
    *,
    snap_tolerance_m: float,
    raw_contact_tolerance_m: float = 1.5,
    relationship: str = "adjacent",
):
    """Make a proven RAW-shared edge use one canonical *smoothed* boundary.

    This deliberately avoids the former ``buffer -> union -> clip`` repair.  That
    boolean growth method could leave one-cell hooks/notches at shared-edge endpoints
    when many DTA were reconciled.  We now replace the corresponding exterior arc
    itself, smoothly blend the two junctions, and only then enforce exact containment
    or adjacency with a final overlay.

    RAW D8 geometry remains topology authority only; staircase coordinates are never
    copied into the visible result.
    """
    if any(g is None or g.is_empty for g in (moving, reference, raw_moving, raw_reference)):
        return moving, {"aligned": False, "reason": "missing_geometry"}

    tol = max(0.0, float(snap_tolerance_m))
    if tol <= 0:
        return moving, {"aligned": False, "reason": "zero_tolerance"}
    if relationship not in {"inside", "adjacent"}:
        return moving, {"aligned": False, "reason": "invalid_relationship"}

    raw_tol = max(0.05, float(raw_contact_tolerance_m))
    try:
        shared_raw = raw_moving.boundary.intersection(raw_reference.boundary)
        shared_lines = _line_parts(shared_raw)
        shared_length = float(sum(line.length for line in shared_lines))
        if shared_length <= max(2.0, raw_tol * 2.0):
            # CRS round-trips can separate an otherwise identical RAW edge by a tiny
            # sub-cell amount.  Recover the moving-side line, but still never use it
            # as display geometry.
            shared_raw = raw_moving.boundary.intersection(raw_reference.boundary.buffer(raw_tol))
            shared_lines = _line_parts(shared_raw)
            shared_length = float(sum(line.length for line in shared_lines))
        if shared_length <= max(2.0, raw_tol * 2.0):
            return moving, {"aligned": False, "reason": "no_shared_raw_edge", "shared_raw_length_m": shared_length}

        # Merge touching RAW segments into meaningful shared runs.  Separate runs are
        # processed independently so a distant shared official-boundary arc is never
        # bridged through unrelated geometry.
        try:
            from shapely.ops import linemerge
            merged = linemerge(union_all(shared_lines))
            runs = _line_parts(merged)
        except Exception:
            runs = shared_lines
        runs = [line for line in runs if line.length > max(2.0, raw_tol * 2.0)]
        runs.sort(key=lambda line: float(line.length), reverse=True)

        aligned = moving
        replacements: list[dict] = []
        for raw_line in runs:
            updated, meta = _replace_shared_exterior_arc(aligned, reference, raw_line, tol)
            if meta.get("replaced"):
                aligned = updated
                replacements.append(meta)

        if not replacements:
            return moving, {
                "aligned": False, "reason": "shared_arc_not_replaced",
                "shared_raw_length_m": shared_length,
            }

        # Arc replacement should already coincide. Overlay is now only the exact
        # topology guarantee, not the mechanism used to construct the shared edge.
        if relationship == "inside":
            aligned = aligned.intersection(reference)
        else:
            aligned = aligned.difference(reference)
        if not aligned.is_valid:
            aligned = make_valid(aligned)
        parts = _polygon_parts(aligned)
        if parts:
            aligned = max(parts, key=lambda g: g.area)
        if aligned is None or aligned.is_empty:
            return moving, {"aligned": False, "reason": "overlay_empty", "shared_raw_length_m": shared_length}

        return aligned, {
            "aligned": True,
            "method": "shared_arc_replacement",
            "shared_raw_length_m": shared_length,
            "shared_run_count": len(replacements),
            "snap_tolerance_m": tol,
            "relationship": relationship,
        }
    except Exception as exc:
        return moving, {"aligned": False, "reason": f"align_failed:{type(exc).__name__}"}

def _coords_join(lines: Iterable[LineString]) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for line in lines:
        part = list(line.coords)
        if not part:
            continue
        if coords and coords[-1] == part[0]:
            coords.extend(part[1:])
        else:
            coords.extend(part)
    return coords


def _forward_arc(ring: LineString, start_distance: float, end_distance: float) -> LineString:
    length = ring.length
    if length <= 0:
        return ring
    start = start_distance % length
    end = end_distance % length
    if end > start:
        return substring(ring, start, end)
    if abs(end - start) < 1e-9:
        p = ring.interpolate(start)
        return LineString([(p.x, p.y), (p.x, p.y)])
    first = substring(ring, start, length)
    second = substring(ring, 0.0, end)
    return LineString(_coords_join([first, second]))


def _reverse(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _official_exterior_rings(official_geom) -> list[LineString]:
    # The ring coordinates are copied directly from official geometry and are never simplified.
    return [LineString(poly.exterior.coords) for poly in _polygon_parts(official_geom)]


def _densify_closed_ring(ring: LineString, max_step_m: float) -> list[tuple[float, float]]:
    """Densify a closed ring only for contact classification; source geometry is not altered."""
    coords = list(ring.coords)
    if len(coords) < 4:
        return coords
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    step = max(2.0, float(max_step_m))
    out: list[tuple[float, float]] = [tuple(coords[0])]
    for a, b in zip(coords[:-1], coords[1:]):
        ax, ay = a; bx, by = b
        length = float(np.hypot(bx - ax, by - ay))
        pieces = max(1, int(np.ceil(length / step)))
        for j in range(1, pieces + 1):
            t = j / pieces
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    if out[-1] != out[0]:
        out.append(out[0])
    return out


def _cyclic_contact_runs(component: Polygon, official_boundary, match_tolerance_m: float):
    """Return ordered alternating exterior-ring runs classified by official-boundary proximity."""
    ring = LineString(component.exterior.coords)
    sample_step = min(30.0, max(8.0, float(match_tolerance_m) / 4.0))
    dense = _densify_closed_ring(ring, sample_step)
    if len(dense) < 4:
        return [], sample_step
    verts = dense[:-1]
    n = len(verts)
    # Shapely 2 ufuncs cross the Python/GEOS boundary once for the full ring.
    # Large downstream DTAs can have tens of thousands of classified segments;
    # constructing and measuring every Point separately dominated cold requests.
    vertices = np.asarray(verts, dtype="float64")
    next_vertices = np.roll(vertices, -1, axis=0)
    midpoints = geometry_points((vertices[:, 0] + next_vertices[:, 0]) * 0.5,
                                (vertices[:, 1] + next_vertices[:, 1]) * 0.5)
    # A direct point-to-MultiLine distance scans a very large official boundary
    # repeatedly. Index its individual segments once, then query every midpoint.
    segment_pairs = []
    for part in _line_parts(official_boundary):
        coordinates = np.asarray(part.coords, dtype="float64")
        if len(coordinates) >= 2:
            segment_pairs.append(np.stack((coordinates[:-1], coordinates[1:]), axis=1))
    if segment_pairs:
        boundary_segments = geometry_linestrings(np.concatenate(segment_pairs, axis=0))
        nearest_pairs, nearest_distances = STRtree(boundary_segments).query_nearest(
            midpoints, return_distance=True, all_matches=False,
        )
        midpoint_distances = np.empty(n, dtype="float64")
        midpoint_distances[nearest_pairs[0]] = nearest_distances
    else:
        midpoint_distances = np.asarray(geometry_distance(midpoints, official_boundary), dtype="float64")
    status = (midpoint_distances <= float(match_tolerance_m)).tolist()
    if all(x == status[0] for x in status):
        return [{"matched": status[0], "line": LineString(dense)}], sample_step

    start = next(i for i in range(n) if status[i] != status[(i - 1) % n])
    runs = []
    cur_status = status[start]
    cur_coords = [verts[start]]
    for k in range(n):
        i = (start + k) % n
        st = status[i]
        if st != cur_status and len(cur_coords) >= 2:
            runs.append({"matched": cur_status, "line": LineString(cur_coords)})
            cur_status = st
            cur_coords = [verts[i]]
        cur_coords.append(verts[(i + 1) % n])
    if len(cur_coords) >= 2:
        runs.append({"matched": cur_status, "line": LineString(cur_coords)})

    # Corridor classification can flicker for one or two raster cells where the FABDEM
    # boundary oscillates around the tolerance. Treat very short gaps as one continuous
    # official contact when the gap itself remains close to the official boundary. This
    # prevents dozens of 30--150 m alternating runs near downstream basin boundaries.
    gap_limit = max(300.0, float(match_tolerance_m) * 2.5)
    contact_limit = float(match_tolerance_m) * 1.6 + sample_step
    for run in runs:
        if run["matched"] or run["line"].length > gap_limit:
            continue
        coords = list(run["line"].coords)
        stride = max(1, int(np.ceil(len(coords) / 64)))
        sampled = np.asarray(coords[::stride], dtype="float64")
        max_dist = float(np.max(geometry_distance(
            geometry_points(sampled[:, 0], sampled[:, 1]), official_boundary,
        ))) if len(sampled) else float("inf")
        if max_dist <= contact_limit:
            run["matched"] = True

    if len(runs) > 1:
        # Re-group in cyclic order after promoting short near-boundary gaps.
        if all(r["matched"] == runs[0]["matched"] for r in runs):
            coords = _coords_join([r["line"] for r in runs])
            if coords and coords[0] != coords[-1]:
                coords.append(coords[0])
            runs = [{"matched": runs[0]["matched"], "line": LineString(coords)}]
        else:
            start = next(i for i in range(len(runs)) if runs[i]["matched"] != runs[(i - 1) % len(runs)]["matched"] )
            ordered = [runs[(start + i) % len(runs)] for i in range(len(runs))]
            merged = []
            for run in ordered:
                if merged and merged[-1]["matched"] == run["matched"]:
                    coords = _coords_join([merged[-1]["line"], run["line"]])
                    merged[-1] = {"matched": run["matched"], "line": LineString(coords)}
                else:
                    merged.append({"matched": run["matched"], "line": run["line"]})
            runs = merged
    return runs, sample_step


def _directed_vertex_distance_stats(source: LineString, target: LineString, max_samples: int = 2500):
    """Approximate directed distance using ordered line vertices with bounded sample cost."""
    coords = list(source.coords)
    if not coords:
        return float("inf"), float("inf")
    stride = max(1, int(np.ceil(len(coords) / max(1, int(max_samples)))))
    sampled = coords[::stride]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    coordinates = np.asarray(sampled, dtype="float64")
    distances = np.asarray(geometry_distance(
        geometry_points(coordinates[:, 0], coordinates[:, 1]), target,
    ), dtype="float64")
    return float(np.max(distances, initial=float("-inf"))), float(np.mean(distances)) if len(distances) else float("inf")


def _best_official_arc(raw_segment: LineString, official_geom, match_tolerance_m: float, sample_step_m: float):
    """Find the exact official arc that best follows one matched raw boundary run."""
    if raw_segment is None or raw_segment.is_empty or raw_segment.length <= 0.5:
        return None
    start = Point(raw_segment.coords[0]); end = Point(raw_segment.coords[-1])
    best = None
    endpoint_limit = float(match_tolerance_m) + max(5.0, sample_step_m * 1.5)
    # `_cyclic_contact_runs` may deliberately absorb a short raster-scale gap
    # into a matched run when it remains within this near-boundary corridor.
    # Keep arc validation compatible with that classification; otherwise a
    # one-cell change in sampling can make the same boundary stitch at 90/150 m
    # but fall back at 120 m.
    contact_limit = float(match_tolerance_m) * 1.6 + sample_step_m
    hausdorff_limit = float(match_tolerance_m) * 1.75 + sample_step_m
    for ring in _official_exterior_rings(official_geom):
        d0 = start.distance(ring); d1 = end.distance(ring)
        if max(d0, d1) > endpoint_limit:
            continue
        da = ring.project(start); db = ring.project(end)
        snap_a = ring.interpolate(da); snap_b = ring.interpolate(db)
        # Both candidates are oriented from raw start -> raw end.
        arc1 = _forward_arc(ring, da, db)
        arc2 = _reverse(_forward_arc(ring, db, da))
        for arc in (arc1, arc2):
            if arc.is_empty or arc.length <= 0.1:
                continue
            raw_len = max(raw_segment.length, 1.0)
            ratio = arc.length / raw_len
            if ratio < 0.20 or ratio > 5.0:
                continue
            # The raw->official direction is authoritative for contact classification.
            # Symmetric Hausdorff is intentionally not used as a hard gate: near an outlet,
            # an exact official arc can contain a short section that is farther from the raw
            # DEM boundary even though every raw matched vertex is inside the configured corridor.
            raw_max, raw_mean = _directed_vertex_distance_stats(raw_segment, arc)
            official_max, official_mean = _directed_vertex_distance_stats(arc, raw_segment)
            if raw_max > max(endpoint_limit + sample_step_m, contact_limit):
                continue
            # Still reject implausible detours on the official candidate. This generous bound
            # permits authoritative boundary correction without allowing basin-scale jumps.
            if official_max > max(2000.0, float(match_tolerance_m) * 16.0):
                continue
            length_penalty = 0.02 * abs(float(arc.length - raw_segment.length))
            endpoint_penalty = 0.5 * (float(d0) + float(d1))
            score = (2.0 * raw_max) + raw_mean + (0.15 * official_mean) + length_penalty + endpoint_penalty
            item = {
                "arc": arc,
                "start": (float(snap_a.x), float(snap_a.y)),
                "end": (float(snap_b.x), float(snap_b.y)),
                "score": float(score),
                "hausdorff_m": float(max(raw_max, official_max)),
                "raw_to_official_max_m": raw_max,
                "official_to_raw_max_m": official_max,
                "length_ratio": float(ratio),
            }
            if best is None or score < best[0]:
                best = (score, item)
    return best[1] if best else None


def _processed_holes(component: Polygon, paek_tolerance_m: float, vw_tolerance_m: float):
    holes = []
    for ring in component.interiors:
        processed = process_fabdem_line(
            LineString(ring.coords),
            paek_tolerance_m=paek_tolerance_m,
            vw_tolerance_m=vw_tolerance_m,
            closed=True,
        )
        if len(processed.coords) >= 4:
            holes.append(list(processed.coords))
    return holes


def _multi_segment_exact_stitch(
    component: Polygon,
    official_geom,
    official_boundary,
    match_tolerance_m: float,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
):
    """
    Stitch any number of official-boundary contact runs while preserving ring order.

    Unlike polygonize-based reconstruction, this routine never creates a third source of
    linework. Every final exterior segment is either a processed FABDEM run or an exact
    official DAS arc. If one official run is unsafe, only that run falls back to FABDEM.
    """
    runs, sample_step = _cyclic_contact_runs(component, official_boundary, match_tolerance_m)
    if not runs:
        return None, {"reason": "no_contact_runs"}

    matched_count = 0
    for run in runs:
        run["accepted"] = False
        run["arc_meta"] = None
        if run["matched"]:
            matched_count += 1
            meta = _best_official_arc(run["line"], official_geom, match_tolerance_m, sample_step)
            if meta is not None:
                run["accepted"] = True
                run["arc_meta"] = meta

    if matched_count == 0:
        return None, {"reason": "no_matched_runs"}
    if not any(r["accepted"] for r in runs):
        return None, {"reason": "no_safe_official_arc", "official_segment_count": matched_count}

    holes = _processed_holes(component, paek_tolerance_m, vw_tolerance_m)

    def build_current():
        lines: list[LineString] = []
        official_len = 0.0
        internal_len = 0.0
        accepted_idx = {i for i, r in enumerate(runs) if r.get("accepted") and r.get("arc_meta")}
        for i, run in enumerate(runs):
            if i in accepted_idx:
                line = run["arc_meta"]["arc"]
                official_len += float(line.length)
            else:
                line = process_fabdem_line(
                    run["line"],
                    paek_tolerance_m=paek_tolerance_m,
                    vw_tolerance_m=vw_tolerance_m,
                    closed=False,
                )
                coords = list(line.coords)
                if len(coords) >= 2:
                    prev_i = (i - 1) % len(runs); next_i = (i + 1) % len(runs)
                    if prev_i in accepted_idx:
                        coords[0] = runs[prev_i]["arc_meta"]["end"]
                    if next_i in accepted_idx:
                        coords[-1] = runs[next_i]["arc_meta"]["start"]
                    line = LineString(coords)
                internal_len += float(line.length)
            lines.append(line)

        coords = _coords_join(lines)
        if len(coords) < 4:
            return None, official_len, internal_len, lines
        if coords[0] != coords[-1]:
            # This should normally be a numerical sub-millimetre closure only. Reject large
            # closure gaps rather than inventing an artificial chord.
            gap = Point(coords[0]).distance(Point(coords[-1]))
            if gap > max(1.0, sample_step * 0.25):
                return None, official_len, internal_len, lines
            coords[-1] = coords[0]
        candidate = Polygon(coords, holes)
        if not candidate.is_valid or candidate.is_empty or candidate.area <= 0:
            return None, official_len, internal_len, lines

        inter = candidate.intersection(component).area
        union_area = candidate.union(component).area
        jaccard = inter / union_area if union_area else 0.0
        area_ratio = candidate.area / component.area if component.area else 0.0
        if jaccard < 0.68 or not (0.68 <= area_ratio <= 1.42):
            return None, official_len, internal_len, lines

        # Provenance guard. Because no make_valid/polygonize is used here, any unexplained
        # boundary indicates a join/closure error and the candidate must be rejected.
        legitimate_parts = []
        for j, line in enumerate(lines):
            buf = 1.0 if j in accepted_idx else 1.5
            legitimate_parts.append(line.buffer(buf, cap_style="flat", join_style="round"))
        legitimate = union_all(legitimate_parts)
        unexplained = candidate.boundary.difference(legitimate).length
        if unexplained > max(3.0, candidate.boundary.length * 0.002):
            return None, official_len, internal_len, lines
        return (candidate, float(jaccard), float(area_ratio)), official_len, internal_len, lines

    rejected = sum(1 for r in runs if r["matched"] and not r["accepted"])
    # Try with every safe arc. If the assembled ring fails, reject the weakest official arc
    # one-by-one rather than discarding all valid official matching.
    while any(r["accepted"] for r in runs):
        built, official_len, internal_len, _ = build_current()
        if built is not None:
            candidate, jaccard, area_ratio = built
            accepted = [r for r in runs if r["accepted"]]
            return candidate, {
                "method": "multi_segment_exact_official_arc",
                "jaccard": jaccard,
                "area_ratio": area_ratio,
                "official_arc_length_m": float(official_len),
                "internal_length_m": float(internal_len),
                "official_segment_count": int(len(accepted)),
                "rejected_segment_count": int(rejected),
                "internal_segment_count": int(sum(1 for r in runs if not r["accepted"])),
                "max_accepted_hausdorff_m": float(max((r["arc_meta"]["hausdorff_m"] for r in accepted), default=0.0)),
            }
        accepted = [(i, r) for i, r in enumerate(runs) if r["accepted"]]
        if not accepted:
            break
        # Higher score = less trustworthy local match.
        worst_i, _ = max(accepted, key=lambda item: float(item[1]["arc_meta"]["score"]))
        runs[worst_i]["accepted"] = False
        rejected += 1

    return None, {
        "reason": "multi_segment_candidate_rejected",
        "official_segment_count": int(matched_count),
        "rejected_segment_count": int(rejected),
    }


def stitch_watershed_boundary(
    raw_geom,
    official_geom=None,
    *,
    paek_tolerance_m: float,
    vw_tolerance_m: float,
    match_tolerance_m: float = 90.0,
    allow_full_official: bool = False,
):
    """
    Reconstruct a DTA boundary without hard-clipping the FABDEM polygon.

    Workflow:
      raw DTA -> detect official-boundary overlap/corridor -> retain only unmatched FABDEM
      internal boundary -> PAEK-like smooth -> VW simplify ->
      snap endpoints (matching tolerance) -> stitch exact official arc -> validate polygon.

    Official DAS geometry is always copied exactly and is never smoothed or simplified.
    """
    if raw_geom is None or raw_geom.is_empty:
        raise ValueError("raw_geom is empty")
    if not raw_geom.is_valid:
        raw_geom = make_valid(raw_geom)

    diagnostics = StitchDiagnostics(
        match_tolerance_m=float(match_tolerance_m),
        paek_tolerance_m=float(paek_tolerance_m),
        vw_tolerance_m=float(vw_tolerance_m),
        raw_component_count=_component_count(raw_geom),
        raw_vertex_count=_vertex_count(raw_geom),
    )

    def processed_fabdem(g):
        return process_fabdem_polygon(
            g,
            paek_tolerance_m=float(paek_tolerance_m),
            vw_tolerance_m=float(vw_tolerance_m),
        )

    if official_geom is None or official_geom.is_empty:
        final_geom = processed_fabdem(raw_geom)
        diagnostics.mode = "fabdem_paek_vw"
        diagnostics.method = "no_official_geometry"
        diagnostics.internal_boundary_length_m = float(final_geom.boundary.length)
        diagnostics.area_adjustment_m2 = float(final_geom.area - raw_geom.area)
        diagnostics.final_component_count = _component_count(final_geom)
        diagnostics.final_vertex_count = _vertex_count(final_geom)
        return final_geom, diagnostics.as_dict()

    if not official_geom.is_valid:
        official_geom = make_valid(official_geom)
    official_boundary = official_geom.boundary
    raw_boundary = raw_geom.boundary
    matched_length = float(raw_boundary.intersection(official_boundary.buffer(match_tolerance_m)).length)
    diagnostics.matched_raw_boundary_length_m = matched_length
    diagnostics.raw_match_percent = float(100.0 * matched_length / raw_boundary.length) if raw_boundary.length else 0.0

    if matched_length <= 0.5:
        final_geom = processed_fabdem(raw_geom)
        diagnostics.mode = "fabdem_paek_vw"
        diagnostics.method = "no_official_match"
        diagnostics.internal_boundary_length_m = float(final_geom.boundary.length)
        diagnostics.area_adjustment_m2 = float(final_geom.area - raw_geom.area)
        diagnostics.final_component_count = _component_count(final_geom)
        diagnostics.final_vertex_count = _vertex_count(final_geom)
        return final_geom, diagnostics.as_dict()

    raw_official_overlap = raw_geom.intersection(official_geom).area
    official_coverage = raw_official_overlap / official_geom.area if official_geom.area else 0.0
    raw_inside_ratio = raw_official_overlap / raw_geom.area if raw_geom.area else 0.0
    boundary_match_ratio = matched_length / raw_boundary.length if raw_boundary.length else 0.0
    if allow_full_official and official_coverage >= 0.90 and raw_inside_ratio >= 0.90 and boundary_match_ratio >= 0.35:
        final_geom = official_geom
        diagnostics.mode = "official_full_boundary"
        diagnostics.method = "major_basin_outlet"
        diagnostics.official_boundary_length_m = float(official_boundary.length)
        diagnostics.official_boundary_percent = 100.0
        diagnostics.internal_boundary_length_m = 0.0
        diagnostics.area_adjustment_m2 = float(final_geom.area - raw_geom.area)
        diagnostics.final_component_count = _component_count(final_geom)
        diagnostics.final_vertex_count = _vertex_count(final_geom)
        return final_geom, diagnostics.as_dict()

    final_parts = []
    official_used_length = 0.0
    internal_used_length = 0.0
    methods: list[str] = []
    warnings: list[str] = []

    for component in _polygon_parts(raw_geom):
        component_match = component.boundary.intersection(official_boundary.buffer(match_tolerance_m)).length
        if component_match <= 0.5:
            processed = processed_fabdem(component)
            final_parts.extend(_polygon_parts(processed))
            internal_used_length += float(processed.boundary.length)
            methods.append("paek_vw_internal_only")
            continue

        stitched, meta = _multi_segment_exact_stitch(
            component,
            official_geom,
            official_boundary,
            match_tolerance_m,
            paek_tolerance_m,
            vw_tolerance_m,
        )
        if stitched is None:
            # Fail-safe remains conservative, but it is now reached only after segment-level
            # fallback has been attempted. No polygonize or synthetic chord is introduced.
            stitched = processed_fabdem(component)
            warnings.append(
                "Boundary matching multi-segmen tidak lolos pemeriksaan provenance/topologi; "
                f"digunakan DEM PAEK+VW ({meta.get('reason')})."
            )
            methods.append("safe_fabdem_paek_vw_fallback")
            internal_used_length += float(stitched.boundary.length)
            diagnostics.rejected_segment_count += int(meta.get("rejected_segment_count", 0) or 0)
        else:
            methods.append(str(meta.get("method", "multi_segment_exact_official_arc")))
            official_used_length += float(meta.get("official_arc_length_m", 0.0))
            internal_used_length += float(meta.get("internal_length_m", 0.0))
            diagnostics.official_segment_count += int(meta.get("official_segment_count", 0) or 0)
            diagnostics.rejected_segment_count += int(meta.get("rejected_segment_count", 0) or 0)
            diagnostics.internal_segment_count += int(meta.get("internal_segment_count", 0) or 0)
            if int(meta.get("rejected_segment_count", 0) or 0):
                warnings.append(
                    f"{int(meta.get('rejected_segment_count', 0))} segmen boundary menggunakan "
                    "fallback DEM lokal; segmen resmi lain tetap dipertahankan."
                )
        final_parts.extend(_polygon_parts(stitched))

    if not final_parts:
        final_geom = processed_fabdem(raw_geom)
        methods = ["safe_fabdem_paek_vw_fallback"]
        warnings.append("Boundary stitching tidak menghasilkan polygon; DEM PAEK+VW digunakan.")
    else:
        final_geom = union_all(final_parts)
        if not final_geom.is_valid:
            final_geom = make_valid(final_geom)

    diagnostics.mode = "hybrid_stitched" if official_used_length > 0 else "fabdem_paek_vw_fallback"
    diagnostics.method = "+".join(sorted(set(methods)))
    diagnostics.official_boundary_length_m = float(official_used_length)
    diagnostics.internal_boundary_length_m = float(internal_used_length)
    total = official_used_length + internal_used_length
    diagnostics.official_boundary_percent = float(100.0 * official_used_length / total) if total > 0 else 0.0
    diagnostics.area_adjustment_m2 = float(final_geom.area - raw_geom.area)
    diagnostics.final_component_count = _component_count(final_geom)
    diagnostics.final_vertex_count = _vertex_count(final_geom)
    final_boundary = final_geom.boundary
    if final_boundary.length > 0:
        diagnostics.final_official_5m_percent = float(
            100.0 * final_boundary.intersection(official_boundary.buffer(5.0)).length / final_boundary.length
        )
        diagnostics.final_official_tolerance_percent = float(
            100.0 * final_boundary.intersection(official_boundary.buffer(match_tolerance_m)).length / final_boundary.length
        )
    diagnostics.warnings = warnings
    return final_geom, diagnostics.as_dict()
