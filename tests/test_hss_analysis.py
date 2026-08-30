import math
import zipfile
from pathlib import Path

import pytest

from api.services.hss_analysis import calculate_hss
from api.services.hss_workbook import create_hss_workbook


def _sample_analysis():
    return {
        "morphometry": {"area_km2": 100.0},
        "terrain": {
            "longest_flow_path_km": 30.0,
            "centroidal_flowpath_km": 15.0,
            "flowpath_slope": {"longest_flowpath_pct": 1.0},
        },
        "drainage": {
            "main_channel_length_km": 30.0,
            "main_channel_centroidal_length_km": 15.0,
            "main_channel_slope_pct": 1.0,
            "drainage_density_km_per_km2": 1.5,
            "junction_count": 25,
            "gama1": {
                "source_factor": 0.45,
                "source_frequency": 0.55,
                "width_factor": 1.2,
                "relative_upstream_area": 0.35,
                "symmetry_factor": 0.42,
            },
        },
    }


def test_all_hss_methods_return_common_schema():
    payload = calculate_hss(
        point_id="p1",
        label="DTA Uji",
        hydrologic_analysis=_sample_analysis(),
    )
    methods = {method["method"]: method for method in payload["methods"]}
    assert set(methods) == {
        "scs", "nakayasu", "snyder_alexeyev", "gama1", "limantara", "itb1b", "itb2b"
    }
    for method in methods.values():
        assert method["available"] is True
        assert method["Tp_hours"] > 0
        assert method["Qp_m3s"] > 0
        assert len(method["ordinates"]) > 3
        assert math.isfinite(method["volume_m3"])
        assert math.isfinite(method["equivalent_runoff_mm"])
        assert math.isfinite(method["volume_error_pct"])
        assert math.isfinite(method["normalization_factor"])
        assert method["ordinates"][0]["time_hours"] == 0.0


def test_itb_unit_volume_is_conservative():
    payload = calculate_hss(
        point_id="p1",
        label="DTA Uji",
        hydrologic_analysis=_sample_analysis(),
        methods=["itb1b", "itb2b"],
    )
    for method in payload["methods"]:
        assert method["available"] is True
        assert abs(method["equivalent_runoff_mm"] - 1.0) < 0.01


def test_gama_i_unavailable_without_required_shape_metrics():
    analysis = _sample_analysis()
    analysis["drainage"].pop("gama1")
    payload = calculate_hss(
        point_id="p1",
        label="DTA Uji",
        hydrologic_analysis=analysis,
        methods=["gama1"],
    )
    result = payload["methods"][0]
    assert result["available"] is False
    assert result["warnings"]


def test_calibration_parameters_are_applied_per_request_with_one_global_tr():
    payload = calculate_hss(
        point_id="p1",
        label="DTA Uji",
        hydrologic_analysis=_sample_analysis(),
        methods=["nakayasu", "itb2b"],
        parameters={
            "nakayasu": {"alpha": 3.0},
            "itb2b": {"Ct": 1.2, "Cp": 1.1, "alpha": 2.0, "beta": 0.9},
        },
        global_tr_hours=0.5,
    )
    methods = {method["method"]: method for method in payload["methods"]}
    assert payload["global_tr_hours"] == 0.5
    assert methods["nakayasu"]["parameters"]["alpha"] == 3.0
    assert methods["nakayasu"]["parameters"]["Tr"] == 0.5
    assert methods["itb2b"]["parameters"]["Tr"] == 0.5
    assert methods["itb2b"]["parameters"]["Ct"] == 1.2
    assert methods["itb2b"]["parameters"]["beta"] == 0.9
    assert methods["itb2b"]["parameters"]["Tr"] == 0.5


def test_hss_workbook_has_summary_and_one_sheet_per_available_method(tmp_path: Path):
    payload = calculate_hss(
        point_id="p1",
        label="DTA Uji",
        hydrologic_analysis=_sample_analysis(),
    )
    target = tmp_path / "HSS_DTA_Uji.xlsx"
    create_hss_workbook(payload, target)
    assert target.exists() and target.stat().st_size > 0
    with zipfile.ZipFile(target) as archive:
        workbook = archive.read("xl/workbook.xml").decode("utf-8")
        assert 'name="Ringkasan"' in workbook
        assert 'name="NRCS - SCS"' in workbook
        assert 'name="Nakayasu"' in workbook
        assert 'name="Snyder–Alexeyev"' in workbook
        assert 'name="Gama I"' in workbook
        assert 'name="Limantara"' in workbook
        assert 'name="ITB-1b"' in workbook
        assert 'name="ITB-2b"' in workbook
        assert 'fullCalcOnLoad="1"' in workbook
        worksheet_names = [name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")]
        assert len(worksheet_names) == 8
        worksheet_xml = "".join(archive.read(name).decode("utf-8") for name in worksheet_names)
        assert "<f>" in worksheet_xml
        assert "SUMPRODUCT" in worksheet_xml


def _sni_katulampa_analysis():
    return {
        "morphometry": {"area_km2": 147.35},
        "terrain": {
            "centroidal_flowpath_km": 12.23,
            "longest_flow_path_km": 24.46,
            "flowpath_slope": {"longest_flowpath_pct": 11.2},
        },
        "drainage": {
            "main_channel_length_km": 24.46,
            "main_channel_slope_pct": 11.2,
            "drainage_density_km_per_km2": 2.936,
            "junction_count": 263,
            "gama1": {
                "source_factor": 0.529,
                "source_frequency": 0.505,
                "width_factor": 1.913,
                "relative_upstream_area": 0.540,
                "symmetry_factor": 1.038,
            },
        },
    }


def test_sni_2026_scs_katulampa_benchmark():
    payload = calculate_hss(
        point_id="katulampa",
        label="Katulampa",
        hydrologic_analysis=_sni_katulampa_analysis(),
        methods=["scs"],
        parameters={"scs": {"Ct": 1.0, "Tr": 1.0}},
    )
    method = payload["methods"][0]
    assert method["Tp_hours"] == pytest.approx(6.031, abs=0.002)
    assert method["Qp_m3s"] == pytest.approx(5.090, abs=0.002)
    assert method["equivalent_runoff_mm"] == pytest.approx(1.016, abs=0.003)


def test_sni_2026_snyder_alexeyev_katulampa_benchmark():
    payload = calculate_hss(
        point_id="katulampa",
        label="Katulampa",
        hydrologic_analysis=_sni_katulampa_analysis(),
        methods=["snyder_alexeyev"],
        parameters={"snyder_alexeyev": {"Ct": 1.0, "Cp": 0.70, "Tr": 1.0}},
    )
    method = payload["methods"][0]
    assert method["Tp_hours"] == pytest.approx(5.529, abs=0.002)
    assert method["Qp_m3s"] == pytest.approx(5.130, abs=0.002)
    assert method["equivalent_runoff_mm"] == pytest.approx(1.004, abs=0.003)


def test_sni_2026_gama1_katulampa_core_benchmark():
    payload = calculate_hss(
        point_id="katulampa",
        label="Katulampa",
        hydrologic_analysis=_sni_katulampa_analysis(),
        methods=["gama1"],
        parameters={},
    )
    method = payload["methods"][0]
    assert method["Tp_hours"] == pytest.approx(2.427, abs=0.002)
    assert method["Qp_m3s"] == pytest.approx(9.163, abs=0.002)
    assert method["derived"]["TR_hours"] == pytest.approx(method["Tp_hours"], abs=1e-6)
    assert method["derived"]["TR_equals_Tp"] is True
    assert method["derived"]["global_Tr_used"] is False
    assert method["derived"]["K_hours"] == pytest.approx(3.974, abs=0.003)


def test_sni_2026_itb1b_katulampa_benchmark():
    analysis = {
        "morphometry": {"area_km2": 147.35},
        "terrain": {"longest_flow_path_km": 24.46},
        "drainage": {"main_channel_length_km": 24.46},
    }
    payload = calculate_hss(
        point_id="katulampa",
        label="Katulampa",
        hydrologic_analysis=analysis,
        methods=["itb1b"],
        parameters={"itb1b": {"Ct": 1.0, "Cp": 1.0, "alpha": 3.7, "Tr": 1.0, "k": 10.0}},
    )
    method = payload["methods"][0]
    assert method["Tp_hours"] == pytest.approx(6.03049, abs=0.0002)
    assert method["Qp_m3s"] == pytest.approx(5.09270, abs=0.0002)
    assert method["derived"]["dimensionless_area"] == pytest.approx(1.33275, abs=0.0001)
    assert method["equivalent_runoff_mm"] == pytest.approx(1.0, abs=0.001)


def test_gama_shape_parameters_are_spatially_derived_for_simple_basin():
    from shapely.geometry import LineString, box
    from api.services.hydrologic_analysis import _gama_shape_parameters

    result = _gama_shape_parameters(
        box(0.0, 0.0, 10_000.0, 4_000.0),
        LineString([(0.0, 2_000.0), (10_000.0, 2_000.0)]),
    )
    assert result["width_upstream_km"] == pytest.approx(4.0)
    assert result["width_lower_km"] == pytest.approx(4.0)
    assert result["width_factor"] == pytest.approx(1.0)
    assert result["relative_upstream_area"] == pytest.approx(0.5)
    assert result["symmetry_factor"] == pytest.approx(0.5)


def test_hss_falls_back_to_full_flowpath_when_network_main_channel_is_impossibly_short():
    analysis = _sample_analysis()
    analysis["terrain"]["longest_flow_path_km"] = 132.5
    analysis["terrain"]["centroidal_flowpath_km"] = 84.09
    analysis["terrain"]["flowpath_slope"]["longest_flowpath_pct"] = 0.745
    analysis["drainage"]["main_channel_length_km"] = 0.81
    analysis["drainage"]["main_channel_centroidal_length_km"] = 84.09
    analysis["drainage"]["main_channel_slope_pct"] = 0.0
    payload = calculate_hss(
        point_id="hilir", label="Kali Uji – Hilir", hydrologic_analysis=analysis, methods=["scs"]
    )
    method = payload["methods"][0]
    assert method["available"] is True
    assert method["inputs"]["L"] == pytest.approx(132.5)
    assert method["inputs"]["Lc"] == pytest.approx(84.09)
    assert method["inputs"]["S"] == pytest.approx(0.00745)


def test_hss_workbook_contains_formula_driven_morphometry_and_hss(tmp_path: Path):
    payload = calculate_hss(
        point_id="p1", label="DTA Uji", hydrologic_analysis=_sample_analysis(), methods=["scs", "gama1"]
    )
    target = tmp_path / "formula_hss.xlsx"
    create_hss_workbook(payload, target)
    with zipfile.ZipFile(target) as archive:
        workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
        sheet_xml = archive.read("xl/worksheets/sheet2.xml").decode("utf-8")
        gama_xml = archive.read("xl/worksheets/sheet3.xml").decode("utf-8")
    assert 'fullCalcOnLoad="1"' in workbook_xml
    assert "<f>" in sheet_xml
    assert "MATCH(" in sheet_xml  # SCS dimensionless interpolation stays formula-driven.
    assert "SUMPRODUCT" in sheet_xml
    assert "<f>" in gama_xml
    assert "TR = Tp" in gama_xml
    assert "tidak digunakan dalam persamaan HSS Gama I" in gama_xml
    assert "/$B$" in gama_xml or "*$B$" in gama_xml


def test_gama_shape_parameters_are_anchored_to_outlet_x_even_if_axis_is_reversed():
    """Sri Harto: X is outlet; A=1/4 L, B=3/4 L, WF=WU/WL.

    The basin intentionally widens upstream and has an asymmetric area split so a
    reversed channel axis cannot hide behind WL==WU or RUA==0.5.
    """
    from shapely.geometry import LineString, Point, Polygon
    from api.services.hydrologic_analysis import _gama_shape_parameters

    basin = Polygon([
        (0.0, -1000.0), (0.0, 1000.0),
        (10_000.0, 4000.0), (10_000.0, -4000.0),
    ])
    outlet = Point(0.0, 0.0)
    forward = LineString([(0.0, 0.0), (10_000.0, 0.0)])
    reversed_axis = LineString([(10_000.0, 0.0), (0.0, 0.0)])

    expected = _gama_shape_parameters(basin, forward, outlet_point=outlet)
    actual = _gama_shape_parameters(basin, reversed_axis, outlet_point=outlet)

    assert expected["width_lower_km"] == pytest.approx(3.5)
    assert expected["width_upstream_km"] == pytest.approx(6.5)
    assert expected["width_factor"] == pytest.approx(6.5 / 3.5, abs=1e-5)
    assert expected["upstream_area_km2"] == pytest.approx(27.2, abs=1e-5)
    assert expected["relative_upstream_area"] == pytest.approx(0.544, abs=1e-5)

    for key in (
        "width_lower_km", "width_upstream_km", "width_factor",
        "upstream_area_km2", "relative_upstream_area", "symmetry_factor",
    ):
        assert actual[key] == pytest.approx(expected[key])
    assert actual["axis_reversed_to_outlet"] is True


def test_gama_au_divider_uses_upstream_end_of_lca_not_basin_centroid():
    """AU divider is anchored at the upstream end of Lca on canonical L."""
    from shapely.geometry import LineString, Point, box
    from api.services.hydrologic_analysis import _gama_rua_geometry

    basin = box(0.0, -4000.0, 10_000.0, 4000.0)
    outlet = Point(0.0, 0.0)
    # The basin centroid is (5000, 0), but its closest station on this bent L is
    # (3000, 0).  AU must therefore be divided at the Lca endpoint, not at C.
    main_line = LineString([(0.0, 0.0), (3000.0, 0.0), (3000.0, 3000.0), (10_000.0, 3000.0)])
    lca_station = main_line.project(basin.centroid)
    lca_end = main_line.interpolate(lca_station)

    rua, station, au = _gama_rua_geometry(basin, main_line, outlet_point=outlet)

    assert au is not None
    assert station == pytest.approx(lca_station)
    assert au.boundary.distance(lca_end) == pytest.approx(0.0, abs=1e-6)
    assert au.boundary.distance(basin.centroid) > 1000.0
    assert au.area / 1_000_000.0 == pytest.approx(56.0, abs=1e-5)
    assert rua == pytest.approx(0.7, abs=1e-5)

def test_gama_shape_parameters_include_au_wl_wu_spatial_features():
    from shapely.geometry import LineString, box
    from api.services.hydrologic_analysis import _gama_shape_parameters

    result = _gama_shape_parameters(
        box(0.0, 0.0, 10_000.0, 4_000.0),
        LineString([(0.0, 2_000.0), (10_000.0, 2_000.0)]),
        source_crs="EPSG:3857",
    )
    spatial = result["spatial"]
    assert spatial["crs"] == "EPSG:4326"
    assert spatial["AU"]["geometry"]["type"] == "Polygon"
    assert spatial["WL"]["geometry"]["type"] == "LineString"
    assert spatial["WU"]["geometry"]["type"] == "LineString"
    assert spatial["AU"]["properties"]["value"] == pytest.approx(20.0)
    assert spatial["WL"]["properties"]["value"] == pytest.approx(4.0)
    assert spatial["WU"]["properties"]["value"] == pytest.approx(4.0)


def test_hss_payload_carries_gama_spatial_for_map_and_download():
    analysis = _sample_analysis()
    analysis["drainage"]["gama1"]["spatial"] = {
        "crs": "EPSG:4326",
        "AU": {"type": "Feature", "properties": {"parameter": "AU", "value": 35.0, "unit": "km²"}, "geometry": {"type": "Polygon", "coordinates": [[[110.0, -7.0], [110.1, -7.0], [110.1, -7.1], [110.0, -7.1], [110.0, -7.0]]]}},
        "WL": {"type": "Feature", "properties": {"parameter": "WL", "value": 3.0, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.05], [110.1, -7.05]]}},
        "WU": {"type": "Feature", "properties": {"parameter": "WU", "value": 4.0, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.08], [110.1, -7.08]]}},
    }
    payload = calculate_hss(point_id="p1", label="DTA Uji", hydrologic_analysis=analysis, methods=["gama1"])
    assert payload["schema_version"] == 3
    assert payload["gama1_spatial"]["AU"]["geometry"]["type"] == "Polygon"
    assert payload["gama1_spatial"]["WL"]["geometry"]["type"] == "LineString"
    assert payload["gama1_spatial"]["WU"]["geometry"]["type"] == "LineString"


def test_gama_spatial_export_frames_follow_selected_vector_pipeline():
    from api.services.hss_spatial import gama1_spatial_frames

    payload = {
        "gama1_spatial": {
            "crs": "EPSG:4326",
            "AU": {"type": "Feature", "properties": {"parameter": "AU", "value": 12.5, "unit": "km²"}, "geometry": {"type": "Polygon", "coordinates": [[[110.0, -7.0], [110.01, -7.0], [110.01, -7.01], [110.0, -7.01], [110.0, -7.0]]]}},
            "WL": {"type": "Feature", "properties": {"parameter": "WL", "value": 1.2, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.005], [110.01, -7.005]]}},
            "WU": {"type": "Feature", "properties": {"parameter": "WU", "value": 1.6, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.008], [110.01, -7.008]]}},
        }
    }
    frames = gama1_spatial_frames(payload, point_id="O1", label="Tlogo", source="unit test", target_crs="EPSG:32749")
    assert set(frames) == {"AU", "WL", "WU"}
    assert frames["AU"].geometry.iloc[0].geom_type == "Polygon"
    assert frames["WL"].geometry.iloc[0].geom_type == "LineString"
    assert frames["WU"].geometry.iloc[0].geom_type == "LineString"
    assert frames["AU"].iloc[0]["PARAM"] == "AU"
    assert frames["WL"].iloc[0]["SATUAN"] == "km"
    assert str(frames["AU"].crs).upper() == "EPSG:32749"


def test_gama_wl_wu_are_perpendicular_to_straight_outlet_station_chords():
    """Sri Harto WF construction uses straight X-A/X-B chords for width orientation.

    A and B are still located by cumulative main-channel distance (1/4 L and 3/4 L)
    from outlet X.  On a curved channel the local river tangent is intentionally
    different, so this regression test catches a return to tangent-normal widths.
    """
    import math
    from shapely.geometry import LineString, Point, box
    from api.services.hydrologic_analysis import _gama_cross_section

    basin = box(-2_000.0, -5_000.0, 15_000.0, 15_000.0)
    outlet = Point(0.0, 0.0)
    # Strongly bent channel: local tangents at the quarter/three-quarter stations
    # are not parallel to the straight outlet-to-station chords.
    main_line = LineString([
        (0.0, 0.0),
        (6_000.0, 0.0),
        (6_000.0, 6_000.0),
        (12_000.0, 6_000.0),
    ])

    for fraction in (0.25, 0.75):
        station = main_line.length * fraction
        point = main_line.interpolate(station)
        width, section = _gama_cross_section(
            basin, main_line, station, outlet_point=outlet,
        )
        assert width is not None and width > 0
        assert section is not None

        coords = list(section.coords)
        sx = coords[-1][0] - coords[0][0]
        sy = coords[-1][1] - coords[0][1]
        cx = point.x - outlet.x
        cy = point.y - outlet.y
        dot = sx * cx + sy * cy
        scale = math.hypot(sx, sy) * math.hypot(cx, cy)
        assert scale > 0
        assert abs(dot) / scale < 1e-9

        # The clipped width line must pass through its A/B station.
        assert section.distance(point) == pytest.approx(0.0, abs=1e-7)


def test_gama_shape_parameters_include_auditable_geometric_construction():
    from shapely.geometry import LineString, Point, Polygon
    from api.services.hydrologic_analysis import _gama_shape_parameters

    basin = Polygon([
        (0.0, -1000.0), (0.0, 1000.0),
        (10_000.0, 4000.0), (10_000.0, -4000.0),
    ])
    outlet = Point(0.0, 0.0)
    main_line = LineString([(0.0, 0.0), (5000.0, 1000.0), (10_000.0, 0.0)])
    result = _gama_shape_parameters(basin, main_line, source_crs="EPSG:3857", outlet_point=outlet)
    construction = result["spatial"]["construction"]

    assert set(construction) == {
        "X", "A", "B", "C", "XA", "XB", "X_LCA",
        "WL_PERP", "WU_PERP", "AU_DIVIDER", "PERP_A", "PERP_B", "PERP_AU",
    }
    for key in ("X", "A", "B", "C", "PERP_A", "PERP_B", "PERP_AU"):
        assert construction[key]["geometry"]["type"] == "Point"
    for key in ("XA", "XB", "X_LCA", "WL_PERP", "WU_PERP"):
        assert construction[key]["geometry"]["type"] == "LineString"
    assert construction["AU_DIVIDER"]["geometry"]["type"] in {"LineString", "MultiLineString"}
    assert construction["A"]["properties"]["station_fraction"] == pytest.approx(0.25)
    assert construction["B"]["properties"]["station_fraction"] == pytest.approx(0.75)
    assert construction["PERP_A"]["properties"]["label"] == "⟂"
    assert construction["PERP_AU"]["properties"]["right_angle_at"] == "LCA_END"
    assert "L" not in construction
    assert construction["C"]["properties"]["description"].startswith("Titik terakhir Lca")


def test_gama_grouped_export_frames_are_compact_by_geometry_and_have_no_empty_columns():
    from api.services.hss_spatial import gama1_grouped_frames

    payload = {
        "gama1_spatial": {
            "crs": "EPSG:4326",
            "AU": {"type": "Feature", "properties": {"parameter": "AU", "value": 12.5, "unit": "km²"}, "geometry": {"type": "Polygon", "coordinates": [[[110.0, -7.0], [110.02, -7.0], [110.02, -7.02], [110.0, -7.02], [110.0, -7.0]]]}},
            "WL": {"type": "Feature", "properties": {"parameter": "WL", "value": 1.2, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.005], [110.01, -7.005]]}},
            "WU": {"type": "Feature", "properties": {"parameter": "WU", "value": 1.6, "unit": "km"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.008], [110.015, -7.008]]}},
            "construction": {
                "A": {"type": "Feature", "properties": {"parameter": "A", "kind": "control_point", "value": 2.5, "unit": "km", "description": "Titik A"}, "geometry": {"type": "Point", "coordinates": [110.01, -7.0]}},
                "B": {"type": "Feature", "properties": {"parameter": "B", "kind": "control_point", "value": 7.5, "unit": "km", "description": "Titik B"}, "geometry": {"type": "Point", "coordinates": [110.03, -7.0]}},
                "C": {"type": "Feature", "properties": {"parameter": "C", "kind": "control_point", "value": 5.1, "unit": "km", "description": "Titik C"}, "geometry": {"type": "Point", "coordinates": [110.02, -7.01]}},
                "XA": {"type": "Feature", "properties": {"parameter": "XA", "kind": "reference_axis", "value": 2.1, "unit": "km", "description": "Garis X-A"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.0], [110.01, -7.0]]}},
                "XB": {"type": "Feature", "properties": {"parameter": "XB", "kind": "reference_axis", "value": 6.3, "unit": "km", "description": "Garis X-B"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.0], [110.03, -7.0]]}},
                "X_LCA": {"type": "Feature", "properties": {"parameter": "X_LCA", "kind": "reference_axis", "value": 4.7, "unit": "km", "description": "Garis X-C"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.0], [110.02, -7.01]]}},
            },
        }
    }
    frames = gama1_grouped_frames(payload, point_id="O1", label="DTA Uji", source="© 2026 Unit", target_crs="EPSG:32749")
    assert set(frames) == {"AREA", "GARIS", "TITIK"}
    assert set(frames["AREA"]["PARAM"]) == {"AU"}
    assert set(frames["GARIS"]["PARAM"]) == {"WL", "WU", "XA", "XB", "XC"}
    assert set(frames["TITIK"]["PARAM"]) == {"A", "B", "C"}
    assert all(frames[name].geometry.geom_type.isin({"Polygon", "MultiPolygon"}).all() for name in ["AREA"])
    assert frames["GARIS"].geometry.geom_type.isin({"LineString", "MultiLineString"}).all()
    assert frames["TITIK"].geometry.geom_type.eq("Point").all()
    for frame in frames.values():
        assert "SUMBER" in frame.columns
        assert set(frame["SUMBER"]) == {"© 2026 Unit"}
        assert list(frame.columns)[-2:] == ["SUMBER", "geometry"]
        for column in frame.columns:
            if column != "geometry":
                assert frame[column].notna().any()

def test_characteristic_spatial_uses_one_canonical_l_for_lca_l1085_and_centroid():
    from shapely.geometry import LineString, Point, shape
    from api.services.hydrologic_analysis import _flowpath_spatial_features

    line = LineString([(0.0, 0.0), (4000.0, 0.0), (8000.0, 3000.0), (12_000.0, 3000.0)])
    centroid = Point(6000.0, 2000.0)
    payload = _flowpath_spatial_features(
        line, centroid, "EPSG:3857",
        line_length_m=line.length, centroid_distance_m=line.project(centroid),
    )
    assert payload is not None
    assert set(payload) == {"crs", "L", "LCA", "L10_85", "L10", "L85", "C"}
    l = shape(payload["L"]["geometry"])
    lca = shape(payload["LCA"]["geometry"])
    l1085 = shape(payload["L10_85"]["geometry"])
    c = shape(payload["C"]["geometry"])
    assert l.geom_type == "LineString"
    assert lca.geom_type == "LineString"
    assert l1085.geom_type == "LineString"
    assert c.geom_type == "Point"
    assert payload["L"]["properties"]["value"] == pytest.approx(line.length / 1000.0, abs=1e-4)
    assert payload["LCA"]["properties"]["value"] == pytest.approx(line.project(centroid) / 1000.0, abs=1e-4)
    assert payload["L10_85"]["properties"]["value"] == pytest.approx(line.length * 0.75 / 1000.0, abs=1e-4)


def test_gama_construction_reuses_characteristic_lca_endpoint_for_au_anchor():
    from shapely.geometry import LineString, Point, box, shape
    from api.services.hydrologic_analysis import _flowpath_spatial_features, _gama_shape_parameters

    basin = box(0.0, -3000.0, 10_000.0, 3000.0)
    outlet = Point(0.0, 0.0)
    line = LineString([(0.0, 0.0), (5000.0, 500.0), (10_000.0, 0.0)])
    characteristic = _flowpath_spatial_features(
        line, basin.centroid, "EPSG:3857",
        line_length_m=line.length, centroid_distance_m=line.project(basin.centroid),
    )
    result = _gama_shape_parameters(
        basin, line, source_crs="EPSG:3857", outlet_point=outlet,
        shared_characteristic_spatial=characteristic,
    )
    construction = result["spatial"]["construction"]
    assert "L" not in construction
    assert "C" in construction
    assert "X_LCA" in construction

    lca = shape(characteristic["LCA"]["geometry"])
    axis = shape(construction["X_LCA"]["geometry"])
    c_gama = shape(construction["C"]["geometry"])
    # X-C and Gama-I C terminate at the exact most-upstream endpoint of the
    # Characteristic Lca path. The Characteristic centroid C itself is unchanged.
    assert axis.coords[-1][0] == pytest.approx(lca.coords[-1][0], abs=1e-9)
    assert axis.coords[-1][1] == pytest.approx(lca.coords[-1][1], abs=1e-9)
    assert c_gama.x == pytest.approx(lca.coords[-1][0], abs=1e-9)
    assert c_gama.y == pytest.approx(lca.coords[-1][1], abs=1e-9)

def test_hss_uses_main_river_length_and_slope_when_network_is_valid():
    analysis = _sample_analysis()
    analysis["terrain"]["longest_flow_path_km"] = 42.0
    analysis["terrain"]["flowpath_slope"]["longest_flowpath_pct"] = 0.8
    analysis["drainage"]["main_channel_length_km"] = 30.0
    analysis["drainage"]["main_channel_slope_pct"] = 1.2
    payload = calculate_hss(
        point_id="shared-l", label="DTA Shared L", hydrologic_analysis=analysis, methods=["gama1"],
    )
    method = payload["methods"][0]
    assert method["available"] is True
    assert method["inputs"]["L"] == pytest.approx(30.0)
    assert method["inputs"]["Lc"] == pytest.approx(15.0)
    assert method["inputs"]["S"] == pytest.approx(0.012)


def test_characteristic_grouped_export_frames_are_grouped_and_share_dta_source():
    from api.services.characteristics_spatial import characteristic_grouped_frames

    source = "© 2026 Unit Hidrologi dan Kualitas Air BBWS Serayu Opak diproses 30 Agu 2026 14:45"
    analysis = {
        "characteristic_spatial": {
            "crs": "EPSG:4326",
            "L": {"type": "Feature", "properties": {"value": 10.0, "unit": "km", "description": "Lintasan L"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.0], [110.05, -7.02]]}},
            "LCA": {"type": "Feature", "properties": {"value": 4.0, "unit": "km", "description": "Lintasan Lca"}, "geometry": {"type": "LineString", "coordinates": [[110.0, -7.0], [110.02, -7.01]]}},
            "L10_85": {"type": "Feature", "properties": {"value": 7.5, "unit": "km", "description": "Lintasan 10-85"}, "geometry": {"type": "LineString", "coordinates": [[110.005, -7.002], [110.04, -7.018]]}},
            "C": {"type": "Feature", "properties": {"description": "Titik sentroid"}, "geometry": {"type": "Point", "coordinates": [110.02, -7.01]}},
            "L10": {"type": "Feature", "properties": {"description": "Titik 10%"}, "geometry": {"type": "Point", "coordinates": [110.005, -7.002]}},
            "L85": {"type": "Feature", "properties": {"description": "Titik 85%"}, "geometry": {"type": "Point", "coordinates": [110.04, -7.018]}},
        }
    }

    frames = characteristic_grouped_frames(
        analysis, point_id="O1", label="Kali Progo – Kranggan", source=source, target_crs="EPSG:32749",
    )
    assert set(frames) == {"GARIS", "TITIK"}
    assert set(frames["GARIS"]["PARAM"]) == {"L", "LCA", "L10_85"}
    assert set(frames["TITIK"]["PARAM"]) == {"C", "L10", "L85"}
    for frame in frames.values():
        assert "SUMBER" in frame.columns
        assert set(frame["SUMBER"]) == {source}
        assert list(frame.columns)[-2:] == ["SUMBER", "geometry"]
        assert all(frame[column].notna().any() for column in frame.columns if column != "geometry")


def test_gama_geometry_prefers_characteristic_l_over_main_river_regression():
    """WF/RUA construction must not silently switch to the main-river axis.

    HSS formula inputs may use main-channel L/Lc/S, but Gama-I A/B/C geometry is
    defined from the Characteristic longest-flowpath L/Lca rendered on the map.
    """
    from shapely.geometry import LineString, Point, box
    from api.services.hydrologic_analysis import (
        _flowpath_spatial_features,
        _gama_reference_flowpath,
        _gama_shape_parameters,
    )

    basin = box(-2_000.0, -2_000.0, 14_000.0, 12_000.0)
    outlet = Point(0.0, 0.0)
    # Deliberately different geometries: main river is straight east; Characteristic
    # L bends strongly north, so a regression to main river is immediately detectable.
    main_river = LineString([(0.0, 0.0), (12_000.0, 0.0)])
    characteristic_l = LineString([
        (0.0, 0.0), (4_000.0, 0.0), (4_000.0, 5_000.0), (11_000.0, 8_000.0),
    ])
    lca_station = characteristic_l.length * 0.58
    characteristic = _flowpath_spatial_features(
        characteristic_l,
        characteristic_l.interpolate(lca_station),
        "EPSG:3857",
        line_length_m=characteristic_l.length,
        centroid_distance_m=lca_station,
    )
    reference = _gama_reference_flowpath(main_river, characteristic, "EPSG:3857")
    assert reference is not None
    assert reference.hausdorff_distance(characteristic_l) < 0.01
    assert reference.hausdorff_distance(main_river) > 1_000.0

    result = _gama_shape_parameters(
        basin, reference, source_crs="EPSG:3857", outlet_point=outlet,
        shared_characteristic_spatial=characteristic,
    )
    construction = result["spatial"]["construction"]
    assert construction["A"]["properties"]["station_fraction"] == pytest.approx(0.25)
    assert construction["B"]["properties"]["station_fraction"] == pytest.approx(0.75)
    assert construction["A"]["properties"]["station_distance_km"] == pytest.approx(reference.length * 0.25 / 1000.0, abs=1e-4)
    assert construction["B"]["properties"]["station_distance_km"] == pytest.approx(reference.length * 0.75 / 1000.0, abs=1e-4)
    assert construction["C"]["properties"]["station_distance_km"] == pytest.approx(lca_station / 1000.0, abs=1e-3)


def test_gama_au_wl_wu_share_exact_a_b_c_construction_axes():
    """A=0.25L, B=0.75L, C=end(Lca); result dividers are perpendicular to X-A/B/C."""
    import math
    from shapely.geometry import LineString, Point, box, shape
    from shapely.ops import transform
    from pyproj import Transformer
    from api.services.hydrologic_analysis import _flowpath_spatial_features, _gama_shape_parameters

    basin = box(-3_000.0, -5_000.0, 15_000.0, 15_000.0)
    outlet = Point(0.0, 0.0)
    line = LineString([(0.0, 0.0), (5_000.0, 1_000.0), (7_000.0, 7_000.0), (13_000.0, 9_000.0)])
    lca_station = line.length * 0.61
    characteristic = _flowpath_spatial_features(
        line, line.interpolate(lca_station), "EPSG:3857",
        line_length_m=line.length, centroid_distance_m=lca_station,
    )
    result = _gama_shape_parameters(
        basin, line, source_crs="EPSG:3857", outlet_point=outlet,
        shared_characteristic_spatial=characteristic,
    )
    spatial = result["spatial"]
    construction = spatial["construction"]
    back = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform

    def geom(key):
        return transform(back, shape(construction[key]["geometry"]))
    def result_geom(key):
        return transform(back, shape(spatial[key]["geometry"]))

    a, b, c = geom("A"), geom("B"), geom("C")
    assert a.distance(line.interpolate(line.length * 0.25)) < 0.02
    assert b.distance(line.interpolate(line.length * 0.75)) < 0.02
    assert c.distance(line.interpolate(lca_station)) < 0.02

    x = outlet
    for point, section in ((a, result_geom("WL")), (b, result_geom("WU"))):
        coords = list(section.coords)
        sx, sy = coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]
        ax, ay = point.x - x.x, point.y - x.y
        scale = math.hypot(sx, sy) * math.hypot(ax, ay)
        assert scale > 0
        assert abs(sx * ax + sy * ay) / scale < 1e-7
        assert section.distance(point) < 0.02

    au_divider = geom("AU_DIVIDER")
    # For a MultiLineString use the nearest segment to C.
    parts = list(au_divider.geoms) if hasattr(au_divider, "geoms") else [au_divider]
    section = min(parts, key=lambda g: g.distance(c))
    coords = list(section.coords)
    sx, sy = coords[-1][0] - coords[0][0], coords[-1][1] - coords[0][1]
    cx, cy = c.x - x.x, c.y - x.y
    scale = math.hypot(sx, sy) * math.hypot(cx, cy)
    assert scale > 0
    assert abs(sx * cx + sy * cy) / scale < 1e-7
    assert section.distance(c) < 0.02
