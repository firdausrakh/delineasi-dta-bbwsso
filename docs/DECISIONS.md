# DECISIONS — Catatan Keputusan Project Delineasi DTA

> **Penting:** catatan berikut merupakan **baseline keputusan yang tercermin pada snapshot** atau README historis; bukan notulen rapat atau ADR formal yang ditandatangani. Tanggal asli keputusan individual tidak dipastikan. Untuk keputusan baru gunakan template di akhir file; jangan menambahkan asumsi sebagai keputusan yang telah disetujui.

## Baseline decisions (teramati)

### ADR-001 — Backend GIS tetap Python/FastAPI

- **Status:** implemented pada snapshot.
- **Rationale teramati:** analisis geometri/raster dan output berbasis GeoPandas, Shapely, Rasterio dan modul Python pada `api/core.py` dan `api/services/`.
- **Konsekuensi:** frontend adalah consumer API; migrasi backend merupakan perubahan arsitektur, bukan refactor visual.

### ADR-002 — Dataset runtime predefined/read-only, bukan master data di repo

- **Status:** documented + implemented pattern pada source.
- **Konteks:** README asli menjelaskan migrasi dari Supabase awal ke Cloudflare R2 runtime privat serta asset peta publik; source punya `DATA_BACKEND=local/r2`.
- **Konsekuensi:** data spasial besar dan credential di luar repository; penggunaan data lokal tetap didukung untuk pengembangan.

### ADR-003 — Delineasi hybrid subbasin + D8 dan rekonsiliasi multipoint

- **Status:** implemented.
- **Sumber:** `api/core.py` (`collect_upstream_ids`, `hybrid_watershed_projected`, `constrain_to_official`, `reconcile_final_geometries`).
- **Konsekuensi:** perubahan geometri harus menjaga konsistensi topologi, batas referensi, dan luas kumulatif vs incremental.

### ADR-004 — Analisis numerik tetap berada di server

- **Status:** implemented.
- **Sumber:** endpoint karakteristik, HSS dan model hidrologi pada `api/core.py` dan services terkait.
- **Konsekuensi:** visualisasi/feedback di client boleh berubah, tetapi formula tidak boleh diduplikasi secara independen di JS tanpa kesepakatan.

### ADR-005 — Data kosong bukan nol untuk kalkulasi

- **Status:** enforced di sejumlah parser/model.
- **Sumber:** `validate_records`, raster rainfall validation, tes `test_hydro_model.py` dan `test_hydro_rainfall.py`.
- **Konsekuensi:** output harus menunjukkan tidak tersedia/invalid saat dataset hilang; nol valid pada pengamatan debit atau hujan.

### ADR-006 — HSS multimetode dengan audit volume

- **Status:** implemented.
- **Sumber:** `api/services/hss_analysis.py`, `tests/test_hss_analysis.py`.
- **Konsekuensi:** parameter per DTA/metode, audit integral volume, dan larangan ekspor hasil stale dijaga.

### ADR-007 — Gunakan design tokens dan responsive reflow pada perubahan UI berikutnya

- **Status:** **kebijakan dokumentasi baru**, belum berarti seluruh CSS sudah dimigrasikan.
- **Sumber:** permintaan penataan UI project + `docs/UI_DESIGN_RULES.md`.
- **Konsekuensi:** agent mengikuti hierarchy typography, relative units, dan pemeriksaan browser zoom 100–200%; jangan mengklaim implementasi seluruh komponen telah lolos.

### ADR-008 — Modular Drainage Area Ratio sementara hanya memakai Luas DTA (2026-10-21)

- **Status:** Accepted, temporary.
- **Konteks:** pembacaan descriptor spasial—termasuk `hydro_vectors.gpkg`—menambah waktu proses Modular Drainage Area Ratio di Vercel.
- **Keputusan:** nonaktifkan parameter selain Luas DTA pada UI dan tolak parameter tersebut di API; gunakan luas dari hasil delineasi yang sudah ada.
- **Konsekuensi:** Modular Drainage Area Ratio tidak memuat descriptor spasial maupun konteks hidrogeologi sampai keputusan ini dicabut. Implementasi parameter tetap dipertahankan.
- **Bukti:** `api/core.py`, `templates/spatial.html`, serta regresi `tests/test_hydro_model.py`.

### ADR-009 — Identifier model hidrologi ringkas (2026-10-21)

- **Status:** Accepted.
- **Konteks:** nama model di antarmuka dan kontrak API perlu konsisten, sementara algoritma adalah pilihan di dalam Machine Learning.
- **Keputusan:** gunakan `modar`, `mock`, dan `ml` pada field API `model`; gunakan `ml_algorithm` untuk `random_forest` atau `xgboost`.
- **Konsekuensi:** consumer API harus memperbarui payload model lama; algoritma tetap dipilih eksplisit pada Machine Learning.

## Keputusan yang perlu diverifikasi sebelum diubah

- Batas resmi/CRS dan standar sumber geodata aktif; versi setiap paket data produksi.
- Persamaan dan referensi formal masing-masing HSS/Tc dan parameter model hidrologi.
- Pilihan vendor/kebijakan penyimpanan production, umur cache, pembaruan credential, dan strategi perubahan dataset.
- Target browser, accessibility conformance, observability dan perf budget formal.

## Template keputusan baru

```markdown
### ADR-XXX — [Judul] ([YYYY-MM-DD])
- Status: Proposed / Accepted / Superseded
- Konteks: [masalah + sumber]
- Alternatif: [pilihan yang dipertimbangkan]
- Keputusan: [yang disetujui oleh pemilik project]
- Konsekuensi: [kode, data, UI, uji, migrasi]
- Bukti: [PR, commit, fixture, referensi]
```

Jangan menghapus keputusan historis; tandai `Superseded` beserta referensi penggantinya.
