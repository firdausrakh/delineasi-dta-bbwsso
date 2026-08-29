import unittest
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, box

from api.services.hydrologic_analysis import (
    build_hydrologic_analysis,
    hydrologic_response_class,
    refresh_characteristic_narratives,
    time_of_concentration_metrics,
)
from api.services.characteristics_report import create_characteristics_report
from api.services.characteristics_workbook import create_characteristics_workbook


class HydrologicAnalysisTests(unittest.TestCase):
    def test_geometry_and_network_metrics_work_without_optional_rasters(self):
        streams = gpd.GeoDataFrame(
            [
                {"linkno": 1, "length_m": 1000.0, "slope": 0.01, "strm_order": 2,
                 "geometry": LineString([(0, 0), (1000, 0)])},
                {"linkno": 2, "length_m": 1000.0, "slope": 0.03, "strm_order": 1,
                 "geometry": LineString([(1000, 0), (2000, 0)])},
                {"linkno": 3, "length_m": 1000.0, "slope": 0.02, "strm_order": 1,
                 "geometry": LineString([(1000, 0), (1000, 1000)])},
            ],
            crs="EPSG:32749",
        )
        result = build_hydrologic_analysis(
            geom=box(0, 0, 2000, 1000),
            outlet=Point(0, 0),
            source_crs="EPSG:32749",
            area_km2=2.0,
            streams=streams,
            upstream_ids={1, 2, 3},
            upstream_by_downstream={1: [2, 3]},
            outlet_linkno=1,
            dem_path=None,
            plen_path=None,
        )

        self.assertEqual(result["drainage"]["total_stream_length_km"], 3.0)
        self.assertEqual(result["drainage"]["main_channel_length_km"], 2.0)
        self.assertEqual(result["drainage"]["drainage_density_km_per_km2"], 1.5)
        self.assertEqual(result["morphometry"]["form_factor"], 0.5)
        self.assertFalse(result["terrain"]["available"])
        self.assertIsNone(result["key_indicators"]["curve_number"])
        self.assertIsNone(result["key_indicators"]["time_of_concentration_hours"])
        self.assertEqual(len(result["key_indicator_items"]), 12)
        self.assertEqual(len(result["territory_paragraphs"]), 3)
        self.assertIn("Karakteristik DTA berkembang", result["executive_summary"]["narrative"])
        refresh_characteristic_narratives(result, ".")
        self.assertNotRegex(result["executive_summary"]["narrative"], r"\d,\d")

    def test_tc_methods_are_ordered_and_recommendation_is_domain_based(self):
        result = time_of_concentration_metrics(659.651, 57.008, 3009.6, 26.07, 82.3)
        self.assertEqual(
            [item["label"] for item in result["methods"]],
            ["Kirpich", "NRCS/SCS Lag", "NRCS Velocity Method", "Giandotti", "Témez", "Bransby-Williams", "Kerby", "Izzard", "Passini", "Ventura-Heras", "Johnstone-Cross", "Viparelli"],
        )
        self.assertIsNone(result["methods"][2]["value_hours"])
        self.assertIsNone(result["methods"][7]["value_hours"])
        self.assertTrue(result["recommendation_methods"])
        self.assertNotIn("Bransby-Williams", result["recommendation_methods"])

    def test_hydrologic_response_uses_five_classes(self):
        self.assertEqual(
            [hydrologic_response_class(score) for score in (-4, -3, -2, -1, 0, 1, 2, 3, 4)],
            ["Lambat", "Lambat", "Lambat–Sedang", "Lambat–Sedang", "Sedang", "Sedang–Cepat", "Sedang–Cepat", "Cepat", "Cepat"],
        )

    def test_exports_hide_tc_status_and_justify_prose(self):
        result = {
            "label": "DTA Uji",
            "hydrologic_analysis": {
                "executive_summary": {"response_class": "Sedang", "narrative": "Ringkasan pengujian."},
                "territory_paragraphs": ["Paragraf karakteristik wilayah untuk pengujian."],
                "time_of_concentration": {
                    "methods": [{"label": "Kirpich", "value_hours": 1.5, "status": "Utama", "reason": "Alasan metode."}],
                    "recommended_hours": 1.5,
                    "recommendation_methods": ["Kirpich"],
                    "confidence": "Sedang",
                    "recommendation_basis": "Median metode konsisten.",
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = create_characteristics_workbook([result], root / "characteristics.xlsx")
            report = create_characteristics_report([result], root / "characteristics.pdf")
            with zipfile.ZipFile(workbook) as archive:
                sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
                styles_xml = archive.read("xl/styles.xml").decode("utf-8")
            self.assertNotIn("Utama", sheet_xml)
            self.assertNotIn("DEM", sheet_xml)
            self.assertNotIn("raster", sheet_xml.lower())
            self.assertIn("Alasan metode.", sheet_xml)
            self.assertIn('horizontal="justify"', styles_xml)
            self.assertTrue(report.read_bytes().startswith(b"%PDF"))

    def test_report_escapes_dynamic_text_that_looks_like_markup(self):
        result = {
            "label": "DTA <Uji>",
            "hydrologic_analysis": {
                "executive_summary": {
                    "response_class": "Sedang",
                    "narrative": "Nilai A < B & C > D.",
                },
                "curve_number": {
                    "invalid_pct": 0.0,
                    "interpretations": {
                        "high_cn_area": "Nilai di luar 0<CN≤100 dikeluarkan.",
                    },
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            report = create_characteristics_report(
                [result], Path(directory) / "escaped-characteristics.pdf"
            )
            self.assertTrue(report.read_bytes().startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
