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
