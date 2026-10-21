# Graph Report - delineasi-dta-bbwsso  (2026-10-21)

## Corpus Check
- 77 files · ~115,755 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 24 file(s) not represented in the graph (top: .bat 11, .css 4, (none) 3)

## Summary
- 1517 nodes · 3949 edges · 77 communities (69 shown, 8 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 115 edges (avg confidence: 0.9)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c2cf340a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- spatial.js
- hydro_workbook.py
- runtime_backend.py
- boundary_stitch.py
- test_hydro_runoff.py
- test_hydro_model.py
- test_hss_analysis.py
- isDtaLayerVisible
- openPointPopup
- hss.js
- renderPointCards
- reconcile_results
- core.py
- geopandas
- math
- Any
- prepare_hydro_data.py
- json
- app.py
- _gama_shape_parameters
- reconcile_results
- build_point_result
- hydro-model.js
- export_local_to_r2.py
- applyDtaHighlight
- Point
- CALCULATION — Aturan Perhitungan DTA dan Hidrologi
- largest_polygon_component
- analysis_stream_metrics
- analytics.mjs
- Delineasi DTA BBWS Serayu Opak
- reconcile_final_geometries
- math
- Any
- Delineasi DTA — BBWS Serayu Opak
- Fitur utama
- setDtaColor
- _write_vector_by_format
- package.json
- ShellPerformanceTests
- speed-insights.mjs
- addOperationalLayers
- AGENTS.md — Petunjuk Kerja Coding Agent
- dta
- upload_r2.py
- common.js
- performance.py
- ExistingControl
- README.md
- UI_DESIGN_RULES.md — Standar UI, Typography & Browser Zoom
- pandas
- USERFLOW — Alur Operasi WebGIS Delineasi DTA
- refresh_characteristic_narratives
- UX — Pengalaman Pengguna Delineasi DTA
- ARCHITECTURE — Arsitektur Delineasi DTA
- PRD — Delineasi DTA BBWS Serayu Opak
- Setup Cloudflare R2 dari data lokal
- analysis_stream_metrics
- DATA_MODEL — Model Data Delineasi DTA
- Riwayat arsitektur
- TESTING — Strategi Pengujian dan Regresi Delineasi DTA
- UI — Kontrak Antarmuka WebGIS Delineasi DTA
- SPEC.md — Spesifikasi Ringkas Project
- LatestRequestRegistry
- shell_cache_headers
- GitHub dan Vercel
- Aturan geometri penting
- Arsitektur produksi saat ini
- Struktur Cloudflare R2
- Workflow update setelah production aktif
- Menjalankan aplikasi secara lokal
- prepare_toponim.py
- TODO.md — Backlog Aktif & Verifikasi
- _spatial_geojson_feature

## God Nodes (most connected - your core abstractions)
1. `renderPointCards()` - 43 edges
2. `openExistingPointMenu()` - 32 edges
3. `openPointPopup()` - 32 edges
4. `simulate_runoff()` - 30 edges
5. `analysis_stream_metrics()` - 30 edges
6. `build_hydrologic_analysis()` - 25 edges
7. `addOperationalLayers()` - 25 edges
8. `calculate_hss()` - 24 edges
9. `reconcile_final_geometries()` - 23 edges
10. `Delineasi DTA BBWS Serayu Opak` - 22 edges

## Surprising Connections (you probably didn't know these)
- `1. Konvensi dasar` --references--> `area_km2_equal()`  [INFERRED]
  docs/CALCULATION.md → api/core.py
- `3. Kontrak satuan dan koordinat` --references--> `calculate_hss()`  [INFERRED]
  docs/DATA_MODEL.md → api/services/hss_analysis.py
- `4. Workbook debit sebagai input` --references--> `validate_records()`  [INFERRED]
  docs/DATA_MODEL.md → api/services/hydro_model.py
- `6. FJ Mock dan machine learning` --references--> `simulate_runoff()`  [INFERRED]
  docs/CALCULATION.md → api/services/hydro_runoff.py
- `5. Pipeline delineasi secara garis besar` --references--> `OutletPoint`  [INFERRED]
  docs/ARCHITECTURE.md → api/core.py

## Import Cycles
- None detected.

## Communities (77 total, 8 thin omitted)

### Community 0 - "spatial.js"
Cohesion: 0.03
Nodes (77): applyBasemapVisibility(), applyMapTheme(), BASEMAP_DEFS, BASEMAP_KEYS, boundaryMatchEl, characteristicAnalysisStreamsByPoint, characteristicSpatialByPoint, characteristicStreamPromises (+69 more)

### Community 1 - "hydro_workbook.py"
Cohesion: 0.06
Nodes (36): create_characteristics_report(), _number(), _safe_text(), _cell(), _column_name(), create_characteristics_workbook(), formula(), ExcelFormula (+28 more)

### Community 2 - "runtime_backend.py"
Cohesion: 0.14
Nodes (22): _prewarm_toponym_object(), _download_many(), _download_ref(), ensure_official_rivers_original(), ensure_runtime_object(), ensure_toponym_db_path(), _lazy_object_lock(), _load_local() (+14 more)

### Community 3 - "boundary_stitch.py"
Cohesion: 0.06
Nodes (34): align_expected_shared_boundary(), _best_official_arc(), _blend_complement_to_reference(), _component_count(), _coords_join(), _cumulative_distance(), _cyclic_contact_runs(), _densify_closed_ring() (+26 more)

### Community 4 - "test_hydro_runoff.py"
Cohesion: 0.06
Nodes (54): aggregate(), configuration(), _physical(), validate_records(), cat_distance(), recession_prior(), _estimator(), _fit_mock() (+46 more)

### Community 5 - "test_hydro_model.py"
Cohesion: 0.07
Nodes (39): group_distance(), parse_debit_workbook(), percentile_exc(), simulate(), statistics(), cell_weights(), rainfall_features(), pedotransfer() (+31 more)

### Community 6 - "test_hss_analysis.py"
Cohesion: 0.11
Nodes (42): _adaptive_dt(), _apply_input_overrides(), calculate_hss(), _finite(), _gama1(), _inputs(), _itb1b(), _itb2b() (+34 more)

### Community 7 - "isDtaLayerVisible"
Cohesion: 0.13
Nodes (31): analysisStreamsFeatureCollection(), applyCharacteristicColors(), applyCharacteristicSpatialVisibility(), applyGamaSpatialVisibility(), applyLayerState(), applyPerDtaLayerVisibility(), characteristicAnalysisOrderValues(), characteristicAnyVisible() (+23 more)

### Community 8 - "openPointPopup"
Cohesion: 0.11
Nodes (43): cancelMovePoint(), cancelPointPopupValidation(), cancelScheduledPointPopup(), checkLocation(), clampPointName(), clearDtaSources(), clearLocationPreview(), clearResults() (+35 more)

### Community 9 - "hss.js"
Cohesion: 0.13
Nodes (37): calculateCurrentHss(), chartSeries(), cssColor(), currentPointIds(), derivedMorphometry(), dtaDisplayLabel(), ensureChartRuntime(), extractedMorphometry() (+29 more)

### Community 10 - "renderPointCards"
Cohesion: 0.10
Nodes (49): analysisIndicatorTooltip(), analysisMetric(), analysisResponseTheme(), applyAnalysisLanguage(), applyInterfaceLanguage(), armMovePoint(), bindPointNameLimit(), characteristicAnalyzedPointIds() (+41 more)

### Community 11 - "reconcile_results"
Cohesion: 0.15
Nodes (23): CachedResultsRequest, characteristic_streams(), CharacteristicAnalysisRequest, characteristics_analysis(), delineate(), DelineateRequest, download(), DownloadRequest (+15 more)

### Community 12 - "core.py"
Cohesion: 0.07
Nodes (24): bbwsso_outside_mask(), _clip_original_rivers(), _download_impl(), _dta_export_source(), _ensure_original_river_index(), geocode(), _get_raster_readers(), _haversine_m() (+16 more)

### Community 13 - "geopandas"
Cohesion: 0.09
Nodes (23): characteristic_grouped_frames(), characteristic_spatial_frames(), clipped_analysis_streams(), _drop_all_empty_columns(), _feature_frame(), _merge(), _source_last(), _drop_all_empty_columns() (+15 more)

### Community 14 - "math"
Cohesion: 0.26
Nodes (10): curve_number_metrics(), _geometry_for_dataset(), _hec_hms_terrain_from_dem(), _iter_tile_windows(), _masked_raster(), _native_raster_code_counts(), _native_raster_max(), terrain_metrics() (+2 more)

### Community 15 - "Any"
Cohesion: 0.16
Nodes (16): build_hydrologic_analysis(), _classify(), drainage_metrics(), hydrologic_response_class(), landcover_metrics(), group_pct(), landsystem_metrics(), _main_channel() (+8 more)

### Community 16 - "prepare_hydro_data.py"
Cohesion: 0.14
Nodes (20): prepare_data.sh script, build_crosswalk(), build_topology(), basin_level(), check_cycles(), dataset_dirs(), discover(), extract_single_shp() (+12 more)

### Community 17 - "json"
Cohesion: 0.11
Nodes (6): climate(), daily_rainfall(), fetch_et0(), _text(), prepare(), prepare()

### Community 18 - "app.py"
Cohesion: 0.12
Nodes (4): LazyCoreDispatcher, _load_core_app_sync(), _load_project_dotenv_lightweight(), run_linux_mac.sh script

### Community 19 - "_gama_shape_parameters"
Cohesion: 0.13
Nodes (11): _flowpath_spatial_features(), _gama_cross_section(), _gama_orient_from_outlet(), _gama_perpendicular_sections(), _gama_reference_flowpath(), _gama_rua_geometry(), _gama_rua_section(), _gama_shape_parameters() (+3 more)

### Community 20 - "reconcile_results"
Cohesion: 0.11
Nodes (12): analyze_point_network(), apply_incremental_geometries(), cache_headers(), delineate_multi(), hydro_model_upload(), _parse_uploaded_points_xlsx(), points_from_xlsx(), reconcile_results() (+4 more)

### Community 21 - "build_point_result"
Cohesion: 0.15
Nodes (13): area_km2_equal(), build_point_result(), clean_dta_polygon(), collect_upstream_ids(), _constrain_network_cached(), constrain_to_official(), _hybrid_watershed_cached(), hybrid_watershed_projected() (+5 more)

### Community 22 - "hydro-model.js"
Cohesion: 0.20
Nodes (19): bindReliabilityChart(), commonYears(), detail(), downloadState(), invalidate(), mockSettings(), recipe(), renderDonors() (+11 more)

### Community 23 - "export_local_to_r2.py"
Cohesion: 0.24
Nodes (12): _copy(), _copy_raster_as_cog(), export_hydro_assets(), _json_dump(), _json_load(), main(), _resolve_data_dir(), _resolve_dataset() (+4 more)

### Community 24 - "applyDtaHighlight"
Cohesion: 0.15
Nodes (21): applyDtaHighlight(), cancelDtaHoverDelay(), clearActivePointIfNoOpenCard(), clearDtaHover(), defaultMapCursor(), destroyPointListSortable(), hasOpenSidebarCard(), initPointListSortable() (+13 more)

### Community 25 - "Point"
Cohesion: 0.15
Nodes (10): _flow_side(), location_check(), _nearest_from_tree(), nearest_official_river(), nearest_settlement_toponym(), official_basin_at_point(), _oriented_stream_line(), _river_label() (+2 more)

### Community 26 - "CALCULATION — Aturan Perhitungan DTA dan Hidrologi"
Cohesion: 0.12
Nodes (13): 1. Konvensi dasar, 5. Modular Drainage Area Ratio (DAR), 6. FJ Mock dan machine learning, 7. Aturan perubahan formula, CALCULATION — Aturan Perhitungan DTA dan Hidrologi, 1. Level validasi, 2. Outlet dan request, 3. Geometri/spasial (+5 more)

### Community 27 - "largest_polygon_component"
Cohesion: 0.13
Nodes (9): basin_labels(), _build_basin_label_fc(), largest_polygon_component(), collect(), local_raster_catchment_by_cell(), local_raster_catchment_projected(), locate_outlet_raster_cell(), _nearest_local_raster_cell() (+1 more)

### Community 28 - "analysis_stream_metrics"
Cohesion: 0.20
Nodes (6): _analysis_streams_feature_collection(), analysis_streams_geojson_for_dta(), _clip_stream_network(), _load_analysis_streams(), optional_spatial_path(), _select_intersecting_streams()

### Community 29 - "analytics.mjs"
Cohesion: 0.25
Nodes (16): computeRoute(), detectEnvironment(), escapeRegExp(), getMode(), getScriptSrc(), inject(), isBrowser(), isDevelopment() (+8 more)

### Community 30 - "Delineasi DTA BBWS Serayu Opak"
Cohesion: 0.12
Nodes (15): Catatan repository, Dataset produksi, Delineasi DTA BBWS Serayu Opak, Environment variables, Keamanan, Map assets melalui Vercel rewrite, Model Hidrologi: Modular Drainage Area Ratio, FJ Mock, Machine Learning, Pemeriksaan setelah deploy (+7 more)

### Community 31 - "reconcile_final_geometries"
Cohesion: 0.11
Nodes (9): _branch_partition_candidate(), _branch_partition_score(), _geometry_outside_area(), reconcile_final_geometries(), _topology_edge_snap_tolerance_m(), _topology_raw_contact_tolerance_m(), _topology_tolerance_m2(), _web_mapping() (+1 more)

### Community 32 - "math"
Cohesion: 0.19
Nodes (9): _cached_raster_cell(), _cell_center(), _flowpath_metrics(), sample_flow_point(), _main_channel_from_plen_threshold(), capped_upstream_count(), _raster_cell_area_m2(), _sample_raster() (+1 more)

### Community 33 - "Any"
Cohesion: 0.31
Nodes (6): _compute_hydrologic_analysis_for_result(), _refresh_reconciled_hydrologic_analysis(), _result_frames_for_point(), _result_native_geometry(), _selected_geometry_projected(), to_export_geom()

### Community 34 - "Delineasi DTA — BBWS Serayu Opak"
Cohesion: 0.13
Nodes (15): Baseline Produk, Delineasi DTA — BBWS Serayu Opak, Fungsi Dokumen, Keamanan dan Ketepatan Perhitungan, Lingkup dan Batasan Penting, Menjalankan Aplikasi Secara Lokal, Pengujian dan Verifikasi, Perubahan Kode, Dataset, dan Deploy (+7 more)

### Community 35 - "Fitur utama"
Cohesion: 0.15
Nodes (13): Data Modular Drainage Area Ratio di Cloudflare R2, Delineasi hidrologi, Fitur utama, Hidrograf Satuan Sintetis (HSS), Interaksi outlet dan polygon DTA, Interaksi titik outlet, Jaringan sungai multiscale, Karakterisasi fisik–hidrologi (+5 more)

### Community 36 - "setDtaColor"
Cohesion: 0.19
Nodes (16): applyDtaCustomHex(), applyDtaNativeColor(), ensureDtaColorPicker(), ensureHatchImages(), finishDtaNativeColorPicker(), focusPointColorEditor(), focusPointNameEditor(), hexToRgb() (+8 more)

### Community 37 - "_write_vector_by_format"
Cohesion: 0.24
Nodes (8): _analysis_data_paths(), resolve(), _analysis_stream_data_path(), _geom_to_kml_coords(), _kml_for_gdf(), _write_geojson(), _write_shapefile(), _write_vector_by_format()

### Community 38 - "package.json"
Cohesion: 0.17
Nodes (11): dependencies, @vercel/analytics, @vercel/speed-insights, description, name, private, scripts, build (+3 more)

### Community 40 - "speed-insights.mjs"
Cohesion: 0.36
Nodes (10): computeRoute(), detectEnvironment(), escapeRegExp(), getScriptSrc(), injectSpeedInsights(), isBrowser(), isDevelopment(), loadProps() (+2 more)

### Community 41 - "addOperationalLayers"
Cohesion: 0.15
Nodes (23): addBbwssoOutsideMask(), addOperationalLayers(), appendQuery(), enabledRiverOrdersForCurrentZoom(), ensureRiverLabelData(), lineBase(), mapAssetUrl(), operationalAssetKeyForSource() (+15 more)

### Community 42 - "AGENTS.md — Petunjuk Kerja Coding Agent"
Cohesion: 0.17
Nodes (11): 1. Konteks nyata project, 2. Urutan membaca dokumen (sesuai tugas), 3. Alur kerja setiap tugas, 4. Aturan UI yang tidak dapat dinegosiasikan, 5. Ketepatan data & keamanan, 6. Perintah verifikasi sesuai cakupan, 7. Kebijakan dokumentasi: lengkap, jelas, tidak duplikatif, 8. Definition of Done (+3 more)

### Community 43 - "dta"
Cohesion: 0.25
Nodes (7): entrypoint, root, runtime, rewrites, $schema, services, dta

### Community 44 - "upload_r2.py"
Cohesion: 0.43
Nodes (3): load_project_dotenv(), main(), _upload_tree()

### Community 45 - "common.js"
Cohesion: 0.53
Nodes (4): applyTheme(), isDark(), refreshIcons(), toggleTheme()

### Community 46 - "performance.py"
Cohesion: 0.23
Nodes (3): HeavyJobController, HeavyJobTicket, HeavyJobControllerTests

### Community 50 - "README.md"
Cohesion: 0.22
Nodes (5): DECISIONS — Catatan Keputusan Project Delineasi DTA, Keputusan yang perlu diverifikasi sebelum diubah, Template keputusan baru, Aturan istilah, GLOSSARY — Istilah Delineasi DTA, GIS, dan Hidrologi

### Community 51 - "UI_DESIGN_RULES.md — Standar UI, Typography & Browser Zoom"
Cohesion: 0.17
Nodes (12): 1. Aturan inti (MUST / SHOULD), 2. Satuan CSS: bukan anti-`px`, melainkan anti rigid layout, 3. Hierarki tipografi: enam role, 4. Spacing, proporsi, dan kepadatan informasi, 5. Browser zoom, reflow, dan CSS breakpoints, 6. Ketentuan khusus WebGIS/MapLibre, 7. Aksesibilitas dan interaksi, 8. Cara implementasi di repo ini (+4 more)

### Community 52 - "pandas"
Cohesion: 0.21
Nodes (7): band_dates(), build_river_display_gdf(), _numeric_order(), RiverDisplayTier, _local_data_dir(), main(), _sha256()

### Community 53 - "USERFLOW — Alur Operasi WebGIS Delineasi DTA"
Cohesion: 0.18
Nodes (10): Catatan integritas alur, UF-01 — Buka dan jelajahi peta, UF-02 — Tambah outlet, UF-03 — Delineasi satu atau banyak DTA, UF-04 — Karakteristik fisik–hidrologi, UF-05 — Analisis HSS, UF-06 — Model hidrologi, UF-07 — Unduh hasil (+2 more)

### Community 54 - "refresh_characteristic_narratives"
Cohesion: 0.40
Nodes (4): _narrative_number(), _natural_join(), refresh_characteristic_narratives(), dominant_phrases()

### Community 55 - "UX — Pengalaman Pengguna Delineasi DTA"
Cohesion: 0.20
Nodes (9): 1. Prinsip pengalaman, 2. Pencarian dan pemilihan outlet, 3. Layer, navigasi dan peta, 4. Analisis karakteristik, 5. HSS, 6. Model hidrologi, 7. Unduhan dan feedback, 8. Aksesibilitas dan zoom (+1 more)

### Community 56 - "ARCHITECTURE — Arsitektur Delineasi DTA"
Cohesion: 0.22
Nodes (8): 1. Tujuan dan batas sistem, 2. Peta komponen, 3. Boundary penting, 4. Rute layanan yang teramati, 6. Runtime, deploy, dan caching, 7. Aturan perubahan, 8. Batas audit, ARCHITECTURE — Arsitektur Delineasi DTA

### Community 57 - "PRD — Delineasi DTA BBWS Serayu Opak"
Cohesion: 0.22
Nodes (8): 1. Ringkasan produk, 2. Masalah yang diselesaikan, 3. Kemampuan produk saat ini, 4. Kebutuhan fungsional baseline, 5. Non-functional baseline, 6. Bukan janji produk, 7. Acceptance / perubahan PRD, PRD — Delineasi DTA BBWS Serayu Opak

### Community 58 - "Setup Cloudflare R2 dari data lokal"
Cohesion: 0.22
Nodes (9): 1. Siapkan environment, `23_export_r2_bundle.bat`, `24_upload_r2.bat`, `25_verify_r2.bat`, 2. Buat bucket, 3. Buat credential, 4. Isi `.env`, 5. Jalankan migrasi lengkap (+1 more)

### Community 59 - "analysis_stream_metrics"
Cohesion: 0.29
Nodes (10): analysis_stream_metrics(), best_reference_path(), best_upstream_path(), candidate_path(), precompute_reference_link_metrics(), _reference_candidate_key(), reference_link_metrics(), _assemble_main_channel() (+2 more)

### Community 60 - "DATA_MODEL — Model Data Delineasi DTA"
Cohesion: 0.25
Nodes (7): 1. Domain tree, 3. Kontrak satuan dan koordinat, 4. Workbook debit sebagai input, 5. State frontend dan identitas, 6. Data sumber spasial, 7. Aturan kompatibilitas, DATA_MODEL — Model Data Delineasi DTA

### Community 61 - "Riwayat arsitektur"
Cohesion: 0.25
Nodes (8): 1.0.0.0 — 26 August 2026 — First Web Release, 1.0.0.2 — R2 Performance v2 — 28 August 2026, 1.2.0 — Karakteristik DTA terpadu — 29 August 2026, 1.3.0 — Analisis Hidrograf Satuan Sintetis — 29–30 August 2026, 1.3.1 — Runtime Performance — 30 August 2026, 1.3.2 — Vercel Payload Guard — 30 August 2026, Catatan migrasi arsitektur — 27 August 2026, Riwayat arsitektur

### Community 62 - "TESTING — Strategi Pengujian dan Regresi Delineasi DTA"
Cohesion: 0.25
Nodes (7): 1. Perintah dasar, 2. Inventori modul tes snapshot, 3. Matriks quality gate per jenis perubahan, 4. Acceptance manual browser zoom/UI, 5. Kasus regresi domain yang tidak boleh terlewat, 6. Pelaporan hasil tes, TESTING — Strategi Pengujian dan Regresi Delineasi DTA

### Community 63 - "UI — Kontrak Antarmuka WebGIS Delineasi DTA"
Cohesion: 0.25
Nodes (8): 1. Karakter visual, 2. Bagian interface yang sudah ada, 3. Typography hierarchy wajib, 4. Spacing dan dimensi, 5. State komponen, 6. Responsif dan browser zoom, 7. Kriteria review UI, UI — Kontrak Antarmuka WebGIS Delineasi DTA

### Community 64 - "SPEC.md — Spesifikasi Ringkas Project"
Cohesion: 0.25
Nodes (7): 1. Tujuan & pengguna, 2. Ruang lingkup yang ada pada snapshot, 3. Arsitektur & struktur teknis, 4. Invariant dan batasan penting, 5. Acceptance criteria untuk perubahan, 6. Dokumen lain & konflik, SPEC.md — Spesifikasi Ringkas Project

### Community 66 - "shell_cache_headers"
Cohesion: 0.33
Nodes (3): index(), not_found(), shell_cache_headers()

### Community 67 - "GitHub dan Vercel"
Cohesion: 0.40
Nodes (5): Apa yang masuk GitHub, Deploy Vercel, Environment Variables Vercel, GitHub dan Vercel, Push GitHub

### Community 68 - "Aturan geometri penting"
Cohesion: 0.50
Nodes (4): Aturan geometri penting, Boundary stitching, Multi-DTA, Pembersihan DTA

### Community 69 - "Arsitektur produksi saat ini"
Cohesion: 0.67
Nodes (3): Arsitektur produksi saat ini, Performance v2 untuk Vercel Hobby, Runtime cache R2

### Community 70 - "Struktur Cloudflare R2"
Cohesion: 0.67
Nodes (3): `dta-map-assets` — public/custom domain, `dta-runtime` — private, Struktur Cloudflare R2

### Community 71 - "Workflow update setelah production aktif"
Cohesion: 0.67
Nodes (3): Jika hanya dataset yang berubah, Jika hanya kode/UI yang berubah, Workflow update setelah production aktif

### Community 72 - "Menjalankan aplikasi secara lokal"
Cohesion: 0.67
Nodes (3): Menjalankan aplikasi secara lokal, Opsi A — membaca data lokal langsung, Opsi B — lokal tetapi membaca Cloudflare R2

### Community 74 - "TODO.md — Backlog Aktif & Verifikasi"
Cohesion: 0.33
Nodes (5): Completed, P0 — Dokumentasi dan keamanan perubahan, P1 — Kualitas UI (setelah snapshot baseline visual), P2 — Validasi dan maintainability, TODO.md — Backlog Aktif & Verifikasi

## Knowledge Gaps
- **2 isolated node(s):** `@vercel/analytics`, `@vercel/speed-insights`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 485 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `CALCULATION — Aturan Perhitungan DTA dan Hidrologi` connect `CALCULATION — Aturan Perhitungan DTA dan Hidrologi` to `build_point_result`, `test_hss_analysis.py`, `Any`?**
  _High betweenness centrality (0.107) - this node is a cross-community bridge._
- **What connects `@vercel/analytics`, `@vercel/speed-insights` to the rest of the system?**
  _2 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `spatial.js` be split into smaller, more focused modules?**
  _Cohesion score 0.029519331243469175 - nodes in this community are weakly interconnected._
- **Why does `Delineasi DTA BBWS Serayu Opak` connect `Delineasi DTA BBWS Serayu Opak` to `GitHub dan Vercel`, `Fitur utama`, `Aturan geometri penting`, `Arsitektur produksi saat ini`, `Struktur Cloudflare R2`, `Menjalankan aplikasi secara lokal`, `Workflow update setelah production aktif`, `Setup Cloudflare R2 dari data lokal`, `Riwayat arsitektur`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Should `hydro_workbook.py` be split into smaller, more focused modules?**
  _Cohesion score 0.06 - nodes in this community are weakly interconnected._
- **Why does `DATA_MODEL — Model Data Delineasi DTA` connect `DATA_MODEL — Model Data Delineasi DTA` to `reconcile_results`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Should `runtime_backend.py` be split into smaller, more focused modules?**
  _Cohesion score 0.13513513513513514 - nodes in this community are weakly interconnected._