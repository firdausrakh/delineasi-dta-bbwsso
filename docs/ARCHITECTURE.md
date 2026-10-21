# ARCHITECTURE — Arsitektur Delineasi DTA

> **Basis:** snapshot source `delineasi-dta-bbwsso.zip`, aplikasi versi `1.4.0`; diringkas dari `api/app.py`, `api/core.py`, `api/services/`, `templates/`, `static/`, `vercel.json`, dan dokumentasi runtime yang sudah ada. Ini adalah peta implementasi, bukan rencana penggantian stack.

## 1. Tujuan dan batas sistem

WebGIS mendukung pengolahan outlet dan batas DTA, karakteristik fisik–hidrologi, HSS, model hidrologi, dan ekspor. Interaksi UI memakai HTML/Jinja2, CSS, JavaScript, dan MapLibre; perhitungan GIS/ilmiah dikerjakan backend Python. Dataset besar dipasok terpisah; jangan mengasumsikan semua tersedia pada checkout Git.

## 2. Peta komponen

```text
Browser / MapLibre
  templates/base.html, templates/spatial.html
  static/css/{app,ui-components,spatial,motion}.css
  static/js/{common,spatial,hss,hydro-model}.js
           │ HTTP JSON / file
           ▼
api/app.py — FastAPI lightweight shell, core dispatcher
           ▼
api/core.py — endpoint, validasi request Pydantic,
              delineasi/reconciliation, orkestrasi layanan, download
           ▼
api/services/* — GIS, karakteristik, HSS, hidrologi,
                   report/workbook, performance, runtime backend
           ▼
Runtime dataset (lokal atau Cloudflare R2 privat)
Map assets publik (route /geodata/* lewat konfigurasi deploy)
```

## 3. Boundary penting

| Bagian | Tanggung jawab | File utama |
| --- | --- | --- |
| Shell | Halaman cepat, static/cache, core yang dimuat saat diperlukan | `api/app.py` |
| API + delineasi | Request, snap outlet, raster D8, union subbasin, constraint batas DAS, multipoint topology | `api/core.py`, `api/services/boundary_stitch.py` |
| Karakteristik | DEM, flowpath, drainage, lereng, tutupan lahan, CN, Tc, narasi, spatial layers | `api/services/hydrologic_analysis.py`, `characteristics_spatial.py` |
| HSS | 7 metode, output kurva/parameter, perhitungan volume | `api/services/hss_analysis.py` |
| Model | Modular Drainage Area Ratio / FJ Mock / Machine Learning, iklim dan data soil | `api/services/hydro_model.py`, `hydro_runoff.py`, `hydro_climate.py`, `hydro_spatial.py` |
| Ekspor | Geometri, PDF/XLSX/format spasial, paket hasil | `api/core.py`, `api/services/*_report.py`, `*_workbook.py` |
| Data runtime | Backend `local`/`r2`, materialisasi object, caching | `api/services/runtime_backend.py`; penyiapan `scripts/` |

## 4. Rute layanan yang teramati

| Kelompok | Endpoint |
| --- | --- |
| Shell/status | `GET /`, `GET /api/info`, `GET /api/location-check`, health shell (periksa `api/app.py`) |
| Pencarian & layer | `GET /api/geocode`, `GET /api/basin-labels`, `GET /api/bbwsso-outside-mask`, `GET /api/map-assets/{asset_key}` |
| Outlet/DTA | `POST /api/points-xlsx`, `POST /api/delineate`, `POST /api/delineate-multi`, `POST /api/reconcile-results`, `GET /api/dta/{linkno}` |
| Analisis | `POST /api/characteristics`, `POST /api/characteristic-streams`, `POST /api/hss` |
| Model | `POST /api/hydro-model/workbook`, `POST /api/hydro-model/parameters`, `POST /api/hydro-model` |
| Hasil | `POST /api/download` |

`GET /api/watershed/{linkno}` adalah alias untuk rute DTA. Implementasi aktif tetap menentukan schema final; jangan menganggap dokumentasi ini menggantikan pemeriksaan request model.

## 5. Pipeline delineasi secara garis besar

1. Client membentuk `OutletPoint` (`point_id`, `lon`, `lat`, `source`, label opsional).
2. Server memilih jaringan sungai terdekat dengan radius snap yang tervalidasi.
3. Topologi upstream memakai link/subbasin; bagian outlet dapat dipertegas lewat raster arah aliran lokal D8.
4. Batas dibatasi oleh DAS referensi, geometri dibersihkan, dan variasi smooth/raw disiapkan untuk tampilan/ekspor.
5. Untuk banyak outlet, `reconcile_final_geometries` menangani hubungan hulu–hilir, overlap, dan area incremental.
6. Hasil dikirim ke frontend, dianalisis atau diekspor melalui endpoint lanjutan.

Lihat `docs/CALCULATION.md` dan `docs/VALIDATION.md` sebelum mengubah algoritma atau ambang geometri.

## 6. Runtime, deploy, dan caching

- Konfigurasi backend `DATA_BACKEND=local` atau `DATA_BACKEND=r2`; produksi terdokumentasi menggunakan data predefined/read-only dari Cloudflare R2.
- `Dockerfile.vercel`, `vercel.json`, dan `api/app.py` berperan dalam deployment/container; `/geodata/*` digunakan untuk aset peta publik.
- Lazy materialization/cache mencegah seluruh data raster/vektor besar dimuat pada permintaan awal. `GET /api/info` menampilkan informasi runtime/performance.
- Jangan pindahkan perhitungan berat ke browser, menyalin credential R2 ke client, atau memicu migrasi/upload pada startup.

## 7. Aturan perubahan

- Perubahan schema endpoint: cek Pydantic model di `api/core.py`, pemanggil `static/js/`, dan test terkait.
- Perubahan GIS/algoritma: periksa CRS, topologi hulu–hilir, data kosong, validasi numerik, dan fixture regresi.
- Perubahan WebGIS: baca `docs/UI.md` dan `docs/UI_DESIGN_RULES.md`; kontrol peta harus tetap dapat dipakai saat browser zoom.
- Tidak menambah framework frontend atau memigrasi backend tanpa keputusan terpisah pada `docs/DECISIONS.md`.

## 8. Batas audit

File source menunjukkan struktur di atas; keberhasilan deploy, ketersediaan seluruh R2 object, serta performa production belum diverifikasi oleh dokumen ini. Detail setup historis ada di `docs/TECHNICAL_REFERENCE.md` dan harus dibandingkan dengan konfigurasi aktif.
