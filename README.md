# Delineasi DTA BBWS Serayu Opak

**Version:** `1.3.0`
**Current repository state:** Cloudflare R2 Runtime — Karakteristik DTA + Analisis HSS
**Production hydrology dataset:** threshold jaringan `1 km²`  
**Runtime:** FastAPI + GeoPandas/Shapely/Rasterio + Cloudflare R2 + Vercel Container

Aplikasi web untuk delineasi **Daerah Tangkapan Air (DTA)** berbasis jaringan hidrologi, raster D8 Flow Direction, referensi Batas DAS/Jaringan Sungai resmi, dan penamaan outlet berbasis toponim.

Repository ini adalah kelanjutan dari rilis web pertama `1.0.0.0`. Arsitektur produksi awal menggunakan Supabase PostGIS/Storage; kondisi repository saat ini sudah dimigrasikan menjadi **dataset predefined/read-only berbasis Cloudflare R2**. Supabase tidak lagi diperlukan untuk runtime aplikasi.

> Repository sengaja dibuat ramping. Data spasial besar, data preprocessing, credential, cache runtime, dan bundle hasil ekspor R2 tidak disimpan di GitHub/Vercel. Data master berada di komputer pengelola dan data production berada di Cloudflare R2.

---

## Fitur utama

### Delineasi hidrologi

- Delineasi DTA hybrid berbasis **subbasin predefined + D8 Flow Direction**.
- Snapping outlet ke jaringan hidrologi dan preview jarak snapping.
- Topology upstream berbasis jaringan stream/subbasin yang dimuat ke memori.
- Reconciliation topology untuk hubungan DTA hulu–hilir dan cabang berbeda.
- Boundary stitching konservatif terhadap **Batas DAS acuan**.
- Pembersihan hole kecil `< 62.500 m²` (`6,25 ha`).
- Pemindahan outlet dengan perhitungan ulang hanya pada titik terkait.
- Ekspor DTA beserta atribut dan jaringan sungai pendukung.

### Karakterisasi fisik–hidrologi

- Ringkasan eksekutif kecenderungan respons hidrologi berbasis kombinasi parameter.
- Dua belas indikator kunci tersusun 4 × 3 pada desktop: luas, kemiringan, relief, kerapatan drainase, frekuensi sungai, rasio bifurkasi, faktor bentuk, lintasan terpanjang, kemiringan alur utama, CN, Tc, dan kawasan terbangun.
- Detail teknis topografi, morfometri, jaringan drainase, integral hipsometrik, distribusi kelas lereng, sistem lahan, penggunaan lahan, Curve Number, dan waktu konsentrasi.
- Perbandingan 12 metode waktu konsentrasi dengan status kesesuaian dan rekomendasi berbasis median robust metode yang sesuai domain, bukan rata-rata seluruh metode.
- Laporan PDF dan workbook XLSX satu-sheet dibuat terpisah untuk setiap DTA dan mengambil nilai dari hasil analisis yang sama dengan web.
- Atribut layer DTA hasil ekspor dibuat ringkas: `ID`, `NAMA`, `LUAS_KM2`, `DAS`, `SUNGAI`, dan `SUMBER`; parameter Karakteristik/HSS diekspor pada layer spasial turunannya.
- Nilai berbasis raster aktif otomatis saat `dem.tif` dan `plen.tif` tersedia di `data/shared/`; nilai yang belum memiliki sumber data ditandai belum tersedia.

### Hidrograf Satuan Sintetis (HSS)

- Tombol **Analisis HSS** ditempatkan tepat sebelum **Unduh Hasil** dan bekerja per DTA terpilih.
- Metode tersedia: **NRCS/SCS, Nakayasu, Snyder–Alexeyev, Gama I, Limantara, ITB-1b, dan ITB-2b**.
- Koefisien empiris/kalibrasi dapat diubah per DTA dan per metode tanpa memengaruhi DTA lainnya.
- Hasil menampilkan `Tp`, `Qp`, `Tb`, limpasan ekuivalen, error konservasi volume, grafik perbandingan, dan grafik masing-masing metode.
- Grafik dapat ditampilkan sebagai hasil asli metode atau kurva yang dinormalisasi menjadi volume limpasan 1 mm.
- Perubahan koefisien setelah perhitungan menandai hasil sebagai **perlu dihitung ulang** dan mencegah ekspor hasil lama.
- **Gama I** menurunkan `SF`, `SN`, `WF`, `RUA`, dan `SIM` dari jaringan sungai analisis serta geometri DTA bila data tersedia. Geometri **Luas bagian hulu (AU)**, **Lebar DTA pada ¼ L (WL)**, dan **Lebar DTA pada ¾ L (WU)** tersedia di **Layer & Tampilan** setelah perhitungan, tetapi tetap **nonaktif secara default** sampai pengguna menampilkannya. Konstruksi geometrik pada peta disederhanakan menjadi sumbu audit **X–A, X–B, dan X–C**, dengan **C = ujung paling hulu Lca** untuk konstruksi AU; label sumbu tetap ditampilkan untuk pemeriksaan.
- Pada menu **Unduh Hasil**, HSS merupakan pilihan opsional. Satu workbook `.xlsx` dan PDF dibuat per DTA yang sudah dianalisis; bila Gama I tersedia, data spasialnya dikelompokkan berdasarkan geometri menjadi **AREA** (AU), **GARIS** (WL, WU, X–A, X–B, X–C), dan **TITIK** (A, B, C) pada format yang dicentang.
- Layer **Karakteristik** menampilkan **Lintasan aliran terpanjang (L)**, **lintasan aliran melalui sentroid (Lca)**, **lintasan aliran 10–85 (L10–85)**, **titik sentroid (C)**, serta **Total jaringan sungai** hasil analisis dengan orde Strahler dan ketebalan menurut orde. Gama I memakai geometri longitudinal L/Lca yang sama, sedangkan C tetap merupakan sentroid DTA khusus layer Karakteristik.
- Setiap kartu DTA memiliki satu tombol **Sembunyikan/Tampilkan Layer** sebagai master visibility per DTA. Tombol ini mengendalikan polygon DTA, outlet, layer Karakteristik, serta hasil dan konstruksi Gama I milik DTA tersebut tanpa memengaruhi DTA lain.
- Saat berpindah ke DTA lain pada Analisis HSS, hasil HSS DTA sebelumnya langsung dibersihkan dari panel selama karakteristik DTA baru masih dihitung sehingga tidak ada tabel/grafik sisa yang menyesatkan.
- Pemeriksaan volume menggunakan hujan efektif satuan `1 mm`; HSS asli tidak dinormalisasi secara tersembunyi.

### Interaksi titik outlet

Interaksi penambahan titik menggunakan dua state yang terpisah:

1. **Mulai Tambah / Selesai** — mengaktifkan atau menonaktifkan fungsi klik peta untuk membuat kandidat outlet.
2. **Satu Titik / Multi Titik** — menentukan apakah kandidat berikutnya mengganti `O1` atau ditambahkan sebagai outlet berikutnya.

Perilaku utama:

- saat mode tambah **tidak aktif**, klik area kosong peta tidak membuat titik;
- cursor area peta pada state idle menggunakan perilaku navigasi `grab` / `grabbing`;
- saat **Mulai Tambah** aktif, cursor area peta menjadi `crosshair`;
- hasil Search/Tampilkan Titik pada state idle hanya menjadi **location preview** dan belum didelineasi;
- jika preview sudah ada, menekan **Mulai Tambah** mengaktifkan preview tersebut sebagai kandidat delineasi;
- menekan **Selesai** membatalkan kandidat/request tertunda dan kembali ke state idle tanpa menghapus DTA yang sudah terbentuk;
- mode Multi Titik mendukung sampai `MAX_POINTS` yang didefinisikan backend (saat ini 10 titik).

### Interaksi outlet dan polygon DTA

- Outlet existing tetap memiliki prioritas interaksi.
- Hover outlet menampilkan popup ringkas dan cursor `pointer`.
- Klik outlet membuka kartu/popup DTA terkait.
- Polygon DTA menggunakan **incremental polygon** sebagai hit-area hover/klik, bukan seluruh polygon kumulatif.
- Pendekatan incremental mencegah DTA hilir/terakhir menutupi interaksi DTA lain yang overlap dan menghindari kebutuhan re-order manual.
- Saat mode tambah titik aktif, area polygon dapat digunakan kembali sebagai area kandidat dengan cursor `crosshair`.

### Penamaan titik dan pencarian

- Penamaan outlet otomatis menggunakan database `toponim.sqlite` + **SQLite RTree**.
- Search lokasi menggunakan OpenStreetMap/Nominatim.
- Input koordinat mendukung format desimal dan DMS yang dikenali frontend.
- Nama sungai pada peta dinormalisasi ke format tampilan seperti `K. Serayu`, `K. Luk Ulo`, atau `K. Kedu Anggu Upit`.

### Jaringan sungai multiscale

Jaringan sungai untuk **display peta** dibuat terpisah dari geometri full-resolution yang digunakan backend. Frontend memuat GeoJSON yang berbeda berdasarkan zoom agar geometri ringan pada zoom kecil dan semakin detail saat zoom masuk.

| Rentang zoom | Orde yang tersedia pada tier | Generalisasi display |
|---|---|---:|
| `6.5 – <8.5` | Orde 1 + 2 | `300 m` |
| `8.5 – <10.5` | Orde 1 + 2 | `150 m` |
| `10.5 – <11.5` | Orde 1 + 2 + 3 | `75 m` |
| `11.5 – <12.5` | Orde 1 + 2 + 3 | `35 m` |
| `12.5 – <14` | Semua kelas | `12 m` |
| `>=14` | Semua kelas | full-detail |

Aturan tampil orde:

- **Orde 1 dan Orde 2 mulai tampil bersama pada zoom 6.5**;
- Orde 3 mulai tampil pada zoom 10.5;
- kelas fallback `Orde > 3` mulai tampil pada zoom 12.5;
- garis dan label menggunakan threshold zoom yang sama.

Generalisasi hanya berlaku pada **map asset public**. File `official_rivers_original.gpkg` di runtime tetap full-resolution untuk kebutuhan backend/analisis.

### Prioritas label sungai

Label sungai memakai satu symbol layer dengan prioritas collision:

```text
Orde 1 > Orde 2 > Orde 3 > Orde > 3
```

Pada ruang yang sama, label orde lebih tinggi mendapat prioritas. Label sungai dibuat lebih toleran terhadap meander dengan pengaturan placement yang lebih longgar, tetapi overlap antar-label tetap dikontrol oleh MapLibre.

Saat arsiran DTA aktif, label sungai **tetap ditampilkan di atas hatch** dan tidak disembunyikan hanya karena berada di dalam polygon DTA.

### UI peta

- UI desktop dan mobile responsif.
- Sidebar, search, toolbar, header, dan fullscreen disesuaikan untuk mobile.
- Theme light/dark.
- Peta dasar yang tersedia saat ini:
  - Esri World Topographic;
  - Esri Satellite;
  - OpenStreetMap;
  - Google Maps;
  - Google Satellite;
  - Peta Rupabumi Indonesia (BIG);
  - Esri Dark Gray Canvas;
  - Esri Light Gray Canvas;
  - OpenTopoMap;
  - Tanpa Peta Dasar.

Basemap Esri Streets, CARTO Positron, dan CARTO Dark Matter sudah dihapus dari galeri.

---

## Arsitektur produksi saat ini

```text
DATA MASTER LOKAL
komputer pengelola
       │
       │ 23_export_r2_bundle.bat
       ▼
   r2_bundle/
       │
       │ 24_upload_r2.bat
       ▼
┌────────────────────────────────────────────┐
│              CLOUDFLARE R2                │
│                                            │
│  dta-runtime (PRIVATE)                     │
│  ├── GeoPackage runtime                    │
│  ├── Raster D8/subbasin                    │
│  ├── SQLite toponim                        │
│  └── manifest + metadata                   │
│                                            │
│  dta-map-assets (PUBLIC/custom domain)     │
│  ├── Batas DAS GeoJSON                     │
│  └── Jaringan Sungai multiscale GeoJSON    │
└────────────────────────────────────────────┘
       │                         │
       │ private S3 API          │ public HTTP
       ▼                         ▼
 Vercel Container            Browser / MapLibre
 FastAPI / Python
       │
       ├── GeoPandas / Shapely
       ├── Rasterio / NumPy
       └── SQLite
```

Cloudflare R2 berfungsi sebagai **object storage**, bukan database spasial. Operasi snapping, topology upstream, union polygon, hybrid D8, boundary stitching, dan analisis spasial lainnya tetap dijalankan oleh backend Python.

### Runtime cache R2

Pada `DATA_BACKEND=r2`, backend:

1. membaca `manifest.json` dari bucket private;
2. memakai ukuran dan SHA256 pada manifest untuk memvalidasi cache tanpa `HEAD` berulang;
3. mengunduh tujuh object inti secara paralel, default maksimal empat koneksi;
4. memakai ulang file cache selama versi manifest belum berubah;
5. menunda download `toponim.sqlite` sampai penamaan titik pertama;
6. menunda download `official_rivers_original.gpkg` sampai ekspor dengan jaringan sungai pertama.

Manifest lama yang belum memiliki metadata ukuran/SHA256 tetap didukung melalui fallback `HEAD` + ETag. Bundle baru memakai `schema_version: 3` dan mempunyai `map_assets_version` untuk cache busting map-assets.

Saat bundle baru dibuat, `flowdir.tif` dan `subbasins.tif` dikonversi menjadi **COG kategorikal** dengan resampling overview `NEAREST`. CRS, transform, dimensi, dtype, dan nilai sel base grid diverifikasi tetap identik. Runtime saat ini tetap memakai satu pasangan raster global agar closure topologi dan konsistensi grid dataset existing tidak berubah.

Default cache Vercel berada di:

```text
/tmp/delineasi-dta-runtime/<dataset>/
```

Cache ini bersifat temporary sesuai lifecycle instance/container Vercel.

### Performance v2 untuk Vercel Hobby

Runtime menerapkan perlindungan berikut tanpa mengubah algoritma hidrologi:

- satu job GIS berat aktif per worker secara default;
- antrean terbatas agar request tidak menumpuk tanpa batas;
- request delineasi lama ditandai superseded oleh request browser yang lebih baru;
- request lama juga dihentikan di sela rekonsiliasi topology, bukan hanya saat tracing raster;
- frontend membatalkan koneksi `fetch` delineasi sebelumnya;
- warm-up backend dimulai segera saat HTML diterima sehingga pemeriksaan titik tidak menunggu cold start;
- cache hybrid D8 dan boundary stitching menggunakan `(LINKNO, raster row, raster column)`, bukan koordinat floating point;
- cache topology dan geometry mempunyai batas terpisah;
- cache geometry dibersihkan saat RSS memory melewati threshold;
- hasil karakteristik final memakai cache LRU berbasis hash geometri;
- koneksi SQLite toponim dan koneksi HTTP R2 dipakai ulang pada warm worker;
- map-assets public dimuat langsung dari custom domain R2 tanpa redirect melalui Vercel;
- map-assets memakai versi bundle dan cache immutable;
- statistik job, antrean, RSS, cache, dan transfer R2 tersedia pada `/api/info`.

Pada worker satu vCPU, jangan menaikkan `DTA_MAX_CONCURRENT_HEAVY_JOBS` di atas `1` tanpa benchmark production.

---

## Dataset produksi

Dataset aktif production:

```env
HYDRO_DATASET=1km2
```

Dataset ini menggunakan threshold ekstraksi jaringan sungai minimum `1 km²`. Stream vector, subbasin vector, crosswalk, dan raster ID subbasin berasal dari preprocessing/run yang konsisten.

Data besar tidak disimpan di GitHub, antara lain:

- `flowdir.tif`;
- `subbasins.tif`;
- `hydro_engine.gpkg`;
- `official_reference.gpkg`;
- `official_rivers_original.gpkg`;
- `toponim.sqlite`;
- map-assets GeoJSON;
- dataset preprocessing lokal.

---

## Struktur sumber data lokal

Secara default script migrasi mencari `<repo>/data`.

```text
data/
├── active_dataset.json              # optional
├── processed/
│   └── 1km2/
│       ├── hydro_engine.gpkg
│       │   ├── streams_web
│       │   └── subbasins_web
│       ├── crosswalk.csv
│       ├── metadata.json
│       ├── official_summary.json
│       └── subbasins.tif
├── reference/
│   ├── official_reference.gpkg
│   │   ├── official_basins
│   │   └── official_rivers
│   ├── official_rivers_original.gpkg
│   │   └── jaringan_sungai
│   └── toponim.sqlite
│       ├── toponim
│       └── toponim_rtree
└── shared/
    ├── flowdir.tif
    ├── dem.tif                       # opsional, statistik elevasi dan lereng
    └── plen.tif                      # opsional, longest flow path
```

Jika data berada di luar repository:

```env
LOCAL_DATA_DIR=D:\path\ke\data
HYDRO_DATASET=1km2
```

`LOCAL_DATA_DIR` harus menunjuk langsung ke folder yang memiliki `processed/`, `reference/`, dan `shared/`.

---

## Struktur Cloudflare R2

Gunakan dua bucket terpisah.

### `dta-runtime` — private

```text
dta-runtime/
├── manifest.json
├── datasets/
│   └── 1km2/
│       ├── hydro_engine.gpkg
│       ├── crosswalk.csv
│       ├── metadata.json
│       ├── official_summary.json
│       └── subbasins.tif
├── reference/
│   ├── official_reference.gpkg
│   ├── official_rivers_original.gpkg
│   └── toponim.sqlite
└── shared/
    └── flowdir.tif
```

Bucket ini **jangan dibuat public**. Vercel mengaksesnya menggunakan R2 S3-compatible API dengan token read-only.

### `dta-map-assets` — public/custom domain

```text
dta-map-assets/
├── official_basins.geojson
├── official_rivers_z6_8.geojson
├── official_rivers_z8_10.geojson
├── official_rivers_z10_11.geojson
├── official_rivers_z11_12.geojson
├── official_rivers_z12_14.geojson
└── official_rivers.geojson
```

Bucket ini dapat disajikan melalui R2 public development URL untuk pengujian, tetapi production lebih baik memakai **custom domain Cloudflare**.

---

## Struktur repository

```text
.
├── api/
│   ├── app.py
│   ├── core.py
│   └── services/
│       ├── boundary_stitch.py
│       ├── river_display.py
│       └── runtime_backend.py
├── static/
│   ├── css/
│   └── js/
├── templates/
├── scripts/
│   ├── export_local_to_r2.py
│   ├── upload_r2.py
│   └── verify_r2.py
├── .env.example
├── .gitignore
├── .dockerignore
├── Dockerfile.vercel
├── gunicorn.conf.py
├── requirements.txt
├── run.bat
├── run_linux_mac.sh
├── 21_setup_r2.bat
├── 22_migrate_to_r2.bat
├── 23_export_r2_bundle.bat
├── 24_upload_r2.bat
├── 25_verify_r2.bat
├── git_push.bat
├── vercel.json
└── README.md
```

Folder `supabase/` tidak lagi digunakan pada repository terbaru.

---

## Python dependencies utama

Runtime Python menggunakan antara lain:

- FastAPI;
- GeoPandas;
- Shapely;
- Rasterio;
- NumPy;
- Pandas;
- PyProj;
- Pyogrio;
- SQLite bawaan Python;
- boto3 untuk R2 S3-compatible API;
- Gunicorn + `uvicorn-worker` untuk Vercel Container.

`psycopg` dan `supabase-py` tidak lagi menjadi dependency runtime.

---

## Menjalankan aplikasi secara lokal

### Opsi A — membaca data lokal langsung

Untuk QA tanpa Cloudflare R2:

```env
DATA_BACKEND=local
HYDRO_DATASET=1km2
LOCAL_DATA_DIR=
```

Jika `LOCAL_DATA_DIR` kosong, pastikan struktur `<repo>/data/` tersedia.

Windows:

```text
run.bat
```

Linux/macOS:

```bash
./run_linux_mac.sh
```

Buka:

```text
http://127.0.0.1:8000/
```

Cek runtime:

```text
http://127.0.0.1:8000/api/info
```

Respons harus memuat antara lain:

```json
{
  "app_version": "1.3.0",
  "data_backend": "local",
  "active_dataset": "1km2"
}
```

### Opsi B — lokal tetapi membaca Cloudflare R2

Gunakan untuk menguji kondisi yang sama dengan production:

```env
DATA_BACKEND=r2
HYDRO_DATASET=1km2

R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_RUNTIME_BUCKET=dta-runtime
R2_MANIFEST_KEY=manifest.json
R2_MAP_ASSETS_PUBLIC_BASE=https://data-domain-anda.example
```

Lalu jalankan `run.bat` atau `run_linux_mac.sh`.

---

## Environment variables

Contoh lengkap tersedia di `.env.example`.

| Variable | Production | Keterangan |
|---|---|---|
| `DATA_BACKEND` | wajib | `r2` untuk production, `local` untuk QA lokal |
| `HYDRO_DATASET` | wajib | dataset aktif, saat ini `1km2` |
| `LOCAL_DATA_DIR` | lokal/migrasi | sumber master lokal; kosong = `<repo>/data` |
| `R2_ACCOUNT_ID` | wajib R2 | Cloudflare Account ID |
| `R2_ACCESS_KEY_ID` | wajib R2 | S3 Access Key ID |
| `R2_SECRET_ACCESS_KEY` | wajib R2 | S3 Secret Access Key, server-only |
| `R2_ENDPOINT_URL` | opsional | kosong = endpoint otomatis dari Account ID |
| `R2_RUNTIME_BUCKET` | wajib R2 | default `dta-runtime` |
| `R2_MANIFEST_KEY` | opsional | default `manifest.json` |
| `R2_MAP_ASSETS_BUCKET` | migrasi lokal | default `dta-map-assets` |
| `R2_MAP_ASSETS_PUBLIC_BASE` | disarankan | public/custom domain map-assets tanpa trailing slash |
| `R2_REFRESH_CACHE` | opsional | `0` normal, `1` paksa refresh cache |
| `DTA_RUNTIME_CACHE_DIR` | opsional | kosong = temporary directory sistem |
| `R2_DOWNLOAD_WORKERS` | opsional | default `4`, download object inti secara paralel |
| `R2_VERIFY_DOWNLOAD_SHA256` | opsional | default `0`; `1` untuk hash penuh setelah download |
| `R2_RASTER_COG_COMPRESSION` | opsional migrasi | default `ZSTD`, fallback `DEFLATE` |
| `DTA_MAX_CONCURRENT_HEAVY_JOBS` | opsional | default `1`, sesuai worker satu vCPU |
| `DTA_MAX_QUEUED_HEAVY_JOBS` | opsional | default `4`, batas request GIS yang menunggu |
| `DTA_HEAVY_JOB_QUEUE_TIMEOUT_S` | opsional | default `25` detik |
| `DTA_TOPOLOGY_CACHE_SIZE` | opsional | default `2048`, cache tuple topology ringan |
| `DTA_UPSTREAM_UNION_CACHE_SIZE` | opsional | default `24`, cache polygon upstream |
| `DTA_HYBRID_CACHE_SIZE` | opsional | default `16`, cache hybrid D8 per sel |
| `DTA_BOUNDARY_CACHE_SIZE` | opsional | default `16`, cache boundary stitching per sel |
| `DTA_ANALYSIS_CACHE_SIZE` | opsional | default `3`, cache hasil karakteristik per geometri |
| `DTA_CACHE_PRESSURE_MB` | opsional | default `1400`, threshold pembersihan cache geometry |
| `DTA_PREWARM_TOPONYM` | opsional | default `1`, siapkan database toponim R2 di background |
| `NOMINATIM_USER_AGENT` | disarankan | identitas request Nominatim |
| `GOOGLE_MAPS_TILE_URL` | opsional | endpoint custom jika diperlukan |
| `GOOGLE_SATELLITE_TILE_URL` | opsional | endpoint custom jika diperlukan |

> Jangan pernah memasukkan `R2_SECRET_ACCESS_KEY` ke JavaScript frontend atau repository Git.

---

## Setup Cloudflare R2 dari data lokal

### 1. Siapkan environment

Windows:

```text
21_setup_r2.bat
```

Script membuat virtual environment, memasang dependency, dan menyalin `.env.example` menjadi `.env` bila belum tersedia.

### 2. Buat bucket

Buat:

```text
dta-runtime      → private
dta-map-assets   → public/custom domain
```

Gunakan storage class **Standard** untuk workload runtime/read-heavy.

### 3. Buat credential

Untuk komputer pengelola yang melakukan upload gunakan token dengan akses **Object Read & Write** yang dibatasi pada bucket yang dibutuhkan.

Untuk Vercel production gunakan token terpisah **Object Read only**, minimal terhadap `dta-runtime`.

### 4. Isi `.env`

Contoh minimum pada komputer pengelola:

```env
HYDRO_DATASET=1km2
LOCAL_DATA_DIR=

R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_RUNTIME_BUCKET=dta-runtime
R2_MAP_ASSETS_BUCKET=dta-map-assets
R2_MAP_ASSETS_PUBLIC_BASE=https://data-domain-anda.example
```

### 5. Jalankan migrasi lengkap

```text
22_migrate_to_r2.bat
```

Alur:

```text
23_export_r2_bundle.bat
        ↓
24_upload_r2.bat
        ↓
25_verify_r2.bat
```

#### `23_export_r2_bundle.bat`

Membaca data lokal dan memvalidasi:

- layer `streams_web` dan `subbasins_web`;
- jumlah stream/subbasin/crosswalk;
- Batas DAS dan Jaringan Sungai reference;
- `toponim.sqlite` + SQLite RTree;
- grid `flowdir.tif` dan `subbasins.tif`;
- raster `dem.tif`, `plen.tif`, `cn2.tif`, dan `landcover.tif` untuk analisis karakteristik;
- `streams_analysis.zip` sebagai jaringan sungai analisis (berbeda dari `streams_web` untuk delineasi);
- `landsystem.zip` sebagai sumber ringkasan sistem lahan.
- pembuatan map-assets jaringan sungai multiscale;
- manifest dan SHA-256 file runtime utama.

Tidak ada koneksi Supabase/database eksternal dalam proses ini.

#### `24_upload_r2.bat`

Mengunggah:

```text
r2_bundle/runtime     → dta-runtime
r2_bundle/map-assets  → dta-map-assets
```

#### `25_verify_r2.bat`

Memeriksa kembali object R2, ukuran/checksum, GeoPackage, crosswalk, SQLite RTree, raster grid, raster analisis, jaringan analisis, dan map-assets terhadap bundle/sumber lokal.

---

## GitHub dan Vercel

### Apa yang masuk GitHub

GitHub menyimpan **kode**, bukan data spasial production.

Sebelum commit, pastikan file berikut tidak ikut:

```text
.env
data/
r2_bundle/
*.gpkg
*.tif
*.tiff
credential R2
```

`.gitignore` repository sudah mengabaikan data dan credential utama tersebut.

### Push GitHub

Jika remote repository sudah tersedia, dapat menggunakan:

```text
git_push.bat
```

atau perintah Git biasa:

```bash
git add .
git status
git commit -m "Update Cloudflare R2 runtime"
git push
```

### Environment Variables Vercel

Production minimum:

```env
DATA_BACKEND=r2
HYDRO_DATASET=1km2

R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_RUNTIME_BUCKET=dta-runtime
R2_MANIFEST_KEY=manifest.json
R2_MAP_ASSETS_PUBLIC_BASE=https://data-domain-anda.example
R2_REFRESH_CACHE=0

NOMINATIM_USER_AGENT=bbwsso-delineasi-dta/1.0
```

Gunakan **credential read-only** untuk Vercel.

Tidak perlu mengisi `LOCAL_DATA_DIR` pada production Vercel.

### Deploy Vercel

1. Import repository GitHub ke Vercel.
2. Root Directory = root repository.
3. Gunakan Container runtime sesuai `vercel.json`/`Dockerfile.vercel`.
4. Tambahkan Environment Variables production.
5. Deploy.

Deployment menggunakan `Dockerfile.vercel` dengan Python `3.12-slim-bookworm`, memasang `libexpat1`, dependency Python, lalu menjalankan:

```text
/usr/local/bin/gunicorn --config /app/gunicorn.conf.py api.app:app
```

Gunicorn membuka listening socket terlebih dahulu dan worker kemudian memuat runtime GIS. Pendekatan ini menjaga kompatibilitas Rasterio/GDAL dan startup Vercel Container tanpa mengubah algoritma delineasi.

---

## Workflow update setelah production aktif

### Jika hanya kode/UI yang berubah

```text
Edit kode lokal
    ↓
Git push
    ↓
GitHub
    ↓
Vercel auto-deploy
```

Tidak perlu upload ulang data R2.

### Jika hanya dataset yang berubah

```text
Perbarui data master lokal
    ↓
22_migrate_to_r2.bat
    ↓
Cloudflare R2
    ↓
ETag berubah
    ↓
Runtime memakai object baru
```

Tidak perlu commit data ke GitHub dan biasanya tidak perlu redeploy Vercel.

---

## Pemeriksaan setelah deploy

Setelah URL production tersedia, cek minimal:

- halaman utama dapat dimuat;
- `/api/info` mengembalikan `app_version: 1.3.0`;
- `data_backend` adalah `r2`;
- `active_dataset` adalah `1km2`;
- Batas DAS tampil;
- jaringan sungai multiscale tampil sesuai zoom;
- Orde 1 + 2 tampil bersama pada zoom awal yang ditentukan;
- label sungai tetap tampil saat hatch DTA aktif;
- prioritas collision label mengikuti orde sungai;
- Search Nominatim bekerja;
- preview lokasi tidak langsung delineasi saat mode tambah belum aktif;
- Mulai Tambah/Selesai bekerja;
- Satu Titik dan Multi Titik bekerja;
- hover/klik outlet existing bekerja;
- hit-area polygon DTA menggunakan incremental polygon;
- pindah outlet tidak meninggalkan marker lama;
- sidebar/search/mobile/fullscreen tidak saling menutupi;
- ekspor berjalan;
- request lama tidak menumpuk saat outlet dipindahkan berulang;
- `/api/info` menampilkan `heavy_jobs`, `rss_memory_mb`, dan metrik R2;
- browser Console tidak menampilkan error R2/CORS/runtime.

---

## Aturan geometri penting

### Pembersihan DTA

- `MultiPolygon` kumulatif mempertahankan komponen utama yang relevan.
- Hole interior `< 62.500 m²` (`6,25 ha`) diisi.
- Hole lebih besar dipertahankan.
- `make_valid` digunakan untuk pembersihan topologi dasar.

### Boundary stitching

Batas final hanya menggunakan kandidat geometri yang berasal dari:

1. batas hidrologi hasil preprocessing/FABDEM; atau
2. arc Batas DAS acuan.

Sistem menolak stitching yang menghasilkan perubahan bentuk/luas yang tidak aman dan melakukan fallback ke geometri hidrologi yang telah diproses.

### Multi-DTA

- Pada satu aliran, DTA hulu harus berada di dalam DTA hilir.
- Pada cabang berbeda, DTA tidak boleh overlap secara material sebelum pertemuan aliran.
- Shared edge yang terbukti sama dari topologi RAW menggunakan **satu arc batas diperhalus yang kanonik**. Arc pasangan diganti langsung dan junction dibaurkan secara lokal; rekonsiliasi tidak lagi memakai pertumbuhan `buffer -> union/difference` yang dapat membentuk hook/stair-step kecil.
- Setelah rekonsiliasi utama, backend menjalankan **auto-repair topologi final**: containment hulu-hilir diselesaikan dengan intersection dan overlap antar-cabang dipartisi secara deterministik tanpa fallback ke batas RAW bergerigi.
- QA hanya memberi status gagal bila residual masih melebihi toleransi skala raster setelah auto-repair. Sliver numerik sub-sel tidak lagi memunculkan status "Periksa batas".
- Setelah perubahan outlet, topology direkonsiliasi kembali sebelum hasil final ditampilkan/diunduh.
- Interaksi polygon pada frontend menggunakan **incremental area** agar setiap DTA tetap dapat dipilih tanpa tertutup seluruh polygon DTA lain.

---

## Penamaan titik

Search bar menggunakan OpenStreetMap/Nominatim untuk mencari lokasi.

Toponim internal digunakan untuk nama awal outlet dengan prioritas data yang telah disiapkan pada `toponim.sqlite`. Lookup proximity menggunakan SQLite RTree lalu jarak kandidat dihitung di Python.

Secara umum tier penamaan mempertahankan prioritas:

```text
Tier utama:
- Permukiman Lainnya
- Ibukota Desa
- Ibukota Kecamatan

Fallback:
Desa → Kecamatan → Kota → Ibukota Kabupaten
```

Jika arah aliran dapat ditentukan secara stabil, logika penamaan dapat memprioritaskan kandidat yang konsisten terhadap posisi outlet/sungai.

---

## Map assets dan CORS

Jika `R2_MAP_ASSETS_PUBLIC_BASE` menggunakan domain yang berbeda dari aplikasi, bucket `dta-map-assets` harus mengizinkan origin aplikasi melalui CORS untuk request `GET`/`HEAD`.

Untuk development lokal, origin yang umum:

```text
http://127.0.0.1:8000
http://localhost:8000
```

Untuk production tambahkan domain Vercel/custom domain aplikasi.

Performance v2 mengarahkan browser langsung ke custom domain tersebut. Aktifkan Cloudflare Cache/Cache Everything untuk hostname map-assets. Script upload memberi `Cache-Control: public, max-age=31536000, immutable`, sedangkan `map_assets_version` pada manifest membuat URL baru ketika isi bundle berubah.

Setelah mengubah kebijakan CORS atau cache pada bucket yang sudah pernah diakses, purge cache hostname map-assets sebelum QA ulang.

Jika `R2_MAP_ASSETS_PUBLIC_BASE` dikosongkan saat local testing, backend dapat melayani map asset dari runtime data sebagai fallback sesuai implementasi endpoint yang tersedia.

---

## Keamanan

- Jangan commit `.env`.
- Jangan commit `R2_SECRET_ACCESS_KEY`.
- Jangan expose credential R2 ke JavaScript/browser.
- `dta-runtime` harus private.
- `dta-map-assets` hanya berisi asset display yang memang boleh public.
- Gunakan token **Read & Write** hanya pada komputer administrasi/migrasi.
- Gunakan token **Read only** pada Vercel production.
- Rotasi token apabila credential pernah terekspos.

---

## Versioning

Project menggunakan skema:

```text
MAJOR.MINOR.PATCH.BUILD
```

Interpretasi:

- **MAJOR** — perubahan besar/arsitektur atau kompatibilitas;
- **MINOR** — fitur baru yang kompatibel;
- **PATCH** — perbaikan bug;
- **BUILD** — revisi deployment/build kecil tanpa perubahan fungsi utama.

Contoh:

```text
1.0.0.0  First Web Release
1.0.1.0  Patch bug
1.1.0.0  Fitur baru
2.0.0.0  Perubahan besar
```

Nomor `p29` sampai `p34` adalah **penanda refinement internal**. Versi aplikasi pada paket ini mengikuti `APP_VERSION` dan saat ini adalah `1.3.2`.

---

## Riwayat arsitektur

Riwayat versi diurutkan dari rilis terbaru hingga rilis web pertama.

### 1.3.0 — Analisis Hidrograf Satuan Sintetis — 29–30 August 2026

- menambahkan HSS NRCS/SCS, Nakayasu, Snyder–Alexeyev, Gama I, Limantara, ITB-1b, dan ITB-2b;
- analisis, parameter kalibrasi, grafik, dan state disimpan per DTA selama sesi;
- perhitungan karakteristik DTA dijalankan secara lazy ketika Karakteristik atau Analisis HSS dibuka, sehingga delineasi utama tetap ringan;
- memperbaiki pemilihan alur utama pada outlet paling hilir agar fragmen sungai pendek tidak menghasilkan L < Lca atau kemiringan 0%;
- menambahkan pemeriksaan konservasi volume serta tampilan kurva asli/ternormalisasi 1 mm;
- grafik HSS menggunakan Chart.js dengan tooltip, pan dan zoom horizontal, serta reset zoom;
- Tr menjadi input global tunggal, sedangkan TR Gama I merupakan waktu naik hasil perhitungan dan diperlakukan sebagai Tp;
- parameter morfometri sumber HSS dapat disesuaikan dan di-reset, sedangkan parameter turunan (`D`, `SF`, `SN`, `WF`, `RUA`, `SIM`) dihitung otomatis;
- setiap kartu metode HSS dan panel parameter morfometri dapat dibuka/tutup untuk mempertahankan tampilan ringkas;
- menambahkan ekstraksi dan visualisasi spasial Gama I: **AU**, **WL**, dan **WU** tersedia sebagai kontrol pada **Layer & Tampilan** setelah Gama I berhasil dihitung dan tetap nonaktif secara default sampai dipilih pengguna;
- menyederhanakan konstruksi geometrik Gama I pada peta menjadi **X–A, X–B, dan X–C** (C = ujung paling hulu Lca); hasil ekspor tetap menyimpan titik kontrol A/B/C dan mengelompokkan data berdasarkan tipe geometri;
- menambahkan layer **Karakteristik** untuk **L, Lca, L10–85, C**, serta **Total jaringan sungai** analisis berorde Strahler; Gama I menggunakan geometri L/Lca yang sama, sedangkan C pada Karakteristik tetap merupakan sentroid DTA;
- menambahkan master **show/hide layer per DTA** pada kartu hasil untuk menyembunyikan/menampilkan DTA, outlet, Karakteristik, serta seluruh hasil/konstruksi Gama I milik DTA tersebut;
- memperbaiki state Analisis HSS agar tabel/grafik DTA lama tidak tetap tampil saat karakteristik DTA baru masih dihitung;
- orientasi Gama I mengikuti : **X adalah outlet DTA**; titik **A = 1/4 L** dan **B = 3/4 L** ditentukan sepanjang lintasan aliran terpanjang **L** dari X, kemudian **WL** dan **WU** ditarik melalui A/B tegak lurus terhadap garis lurus **X–A** dan **X–B**; arah digitasi garis sungai tidak boleh membalik WF/RUA/SIM;
- AU/RUA dipilih sebagai bagian DTA di sisi **hulu** garis yang melalui **ujung paling hulu Lca** dan tegak lurus terhadap garis lurus dari outlet **X** ke ujung Lca tersebut; sentroid **C** tetap digunakan sebagai acuan Karakteristik dan tidak dipakai sebagai titik pembagi AU;
- ketika opsi HSS dicentang pada **Unduh Hasil**, data spasial Gama I dikelompokkan menjadi **AREA**, **GARIS**, dan **TITIK**; GeoPackage menyimpan kelompok tersebut sebagai layer, sedangkan Shapefile/GeoJSON/KML dibuat sebagai file terpisah per kelompok;
- menambahkan ekspor HSS PDF dan workbook XLSX per DTA dengan persamaan Excel yang tetap dapat diaudit;
- metode waktu konsentrasi tanpa nilai tidak ditampilkan pada tabel hasil;
- ukuran font tabel karakteristik, narasi wilayah, kartu DTA, tombol aksi, dan kontrol HSS diseragamkan agar elemen utama lebih terbaca;
- layer **Batas DAS**, **Jaringan Sungai**, **Hasil DTA**, **Karakteristik**, dan **HSS Gama I** dibuat collapsible; satu tombol visibilitas global dan satu tombol mata per kartu DTA membantu mengelola tampilan multi-DTA;
- ketebalan garis global diterapkan konsisten pada Batas DAS, Jaringan Sungai, Hasil DTA, Karakteristik, dan Gama I; label mempertahankan halo putih pada mode terang maupun gelap;
- hasil Karakteristik dan HSS dipertahankan selama refresh dalam sesi yang sama, sementara layer turunannya tetap tidak langsung ditampilkan;
- ekspor Karakteristik menyertakan **Total jaringan sungai** yang dipotong batas DTA, **GARIS** (L, Lca, L10–85), dan **TITIK** (C, titik 10%, titik 85%); seluruh layer membawa atribut `SUMBER` yang sama dengan data spasial DTA;
- hover spasial diprioritaskan untuk hasil/turunan DTA (WL/WU, lintasan Karakteristik, AU, lalu DTA) agar objek garis tidak tertutup poligon; jaringan sungai referensi dan Batas DAS tidak diberi hover;
- antarmuka dark mode diseragamkan untuk tombol HSS, label peta, tooltip, serta kartu **Respons Hidrologi** agar kontras tetap jelas;
- startup WebGIS dipisahkan dari inisialisasi engine GIS berat, layer operasional memiliki retry otomatis, dan kandidat titik memberi respons visual segera sambil tetap menunggu validasi `location-check`;
- menambahkan regression test terhadap contoh Katulampa SNI 2415:2026 untuk SCS, Snyder–Alexeyev, dan parameter inti Gama I;
- seluruh penyempurnaan lanjutan HSS dilebur ke versi **1.3.0** agar riwayat rilis tetap satu versi terpadu.

### 1.2.0 — Karakteristik DTA terpadu — 29 August 2026

- respons hidrologi dan 12 indikator kunci diseragamkan pada web, PDF, dan XLSX;
- distribusi lereng dan Curve Number memakai label kelas eksplisit tanpa interval bertumpang tindih;
- metode Tc ditambah NRCS Velocity, Izzard, Johnstone-Cross, dan Viparelli dengan nilai kosong bila input wajib tidak tersedia;
- rekomendasi Tc memakai metode sesuai domain yang konsisten dan mencatat metode dasar serta tingkat keyakinan;
- komponen tooltip informasi dan field pengaturan distandarkan untuk desktop serta mobile;
- tidak ada perubahan object data spasial, sehingga bundle dan upload Cloudflare R2 tidak perlu dijalankan ulang untuk rilis kode ini.

### 1.3.2 — Vercel Payload Guard — 30 August 2026

- payload rekonsiliasi multi-DTA tidak lagi mengirim analisis, RAW polygon, incremental polygon, atau alias geometry yang duplikat;
- RAW hydrology direkonstruksi dari cache raster server ketika topology membutuhkannya;
- koordinat GeoJSON tampilan memakai presisi tetap yang jauh melampaui resolusi raster sumber;
- respons teks Vercel 413/504 ditampilkan sebagai pesan yang dapat dipahami dan tidak lagi memicu `Unexpected token`;
- benchmark empat titik Serayu menurunkan respons multi dari 4,234 MB menjadi 1,671 MB dan request rekonsiliasi menjadi 0,713 MB.

### 1.3.1 — Runtime Performance — 30 August 2026

- validasi lokasi memakai luas DAS yang sudah dihitung saat startup dan tidak lagi menampilkan status “Memeriksa lokasi titik…”;
- cold-start engine dimulai segera setelah HTML diterima, sementara aset shell tetap dapat dirender tanpa menunggu GeoPandas/Rasterio;
- pencarian jaringan karakteristik memakai indeks spasial dan prepared geometry;
- penilaian kecocokan ribuan ruas terhadap lintasan utama dikerjakan secara batch;
- jaringan sungai detail dimuat terpisah di background agar hasil numerik tidak tertahan payload GeoJSON besar;
- hasil karakteristik memakai cache LRU berbasis hash geometri dan object R2 independen diunduh paralel;
- pada benchmark lokal Hilir Serayu 1 km², karakteristik cold turun dari sekitar 29,7 detik menjadi 4,4 detik dan cache ulang sekitar 19 ms.

### 1.0.0.2 — R2 Performance v2 — 28 August 2026

- download object inti R2 paralel dan manifest-first cache validation;
- toponim serta jaringan sungai asli untuk ekspor dimuat secara lazy;
- map-assets dikirim langsung dari custom domain R2 dengan bundle version;
- request delineasi lama dibatalkan/superseded;
- job GIS berat dibatasi sesuai satu vCPU;
- cache hybrid dan boundary menggunakan sel raster;
- cache geometry dibatasi dan dapat dibersihkan berdasarkan RSS memory;
- observability antrean, cache, memory, serta I/O R2 ditambahkan.

### 1.0.0.0 — 26 August 2026 — First Web Release

Rilis web pertama menggunakan FastAPI/Vercel Container dengan Supabase PostGIS + Storage sebagai sumber data production. Baseline tersebut sudah mencakup hybrid D8, topology multi-DTA, conservative boundary stitching, penamaan toponim, ekspor, dan UI desktop/mobile.

### Catatan migrasi arsitektur — 27 August 2026

Setelah rilis web pertama, runtime data dimigrasikan dari Supabase menjadi arsitektur predefined/read-only:

```text
Data lokal master → Cloudflare R2 → Vercel/FastAPI
```

Perubahan utama:

- Supabase PostGIS/Storage tidak lagi menjadi dependency runtime;
- sumber migrasi R2 langsung dari data lokal;
- `psycopg` dan `supabase-py` dihapus dari requirements;
- data runtime private disimpan di `dta-runtime`;
- map-assets public disimpan di `dta-map-assets`;
- runtime memakai cache berbasis R2 ETag;
- toponim memakai SQLite + RTree;
- jaringan sungai display dibuat menjadi enam tier multiscale/generalized;
- mode tambah titik dipisahkan dari mode Satu/Multi Titik;
- interaksi polygon DTA kembali menggunakan incremental polygon pada refinement `p33`.

---

## Catatan repository

File berikut sengaja tidak dibundel ke GitHub production repository:

- data source/processed lokal;
- `toponim.sqlite`;
- GeoPackage/TIFF/GeoJSON besar;
- `r2_bundle/`;
- credential `.env`;
- benchmark/QA historis yang tidak diperlukan runtime;
- file preprocessing khusus yang tidak diperlukan deployment.

Master dataset dan arsip pengembangan sebaiknya disimpan terpisah sebagai backup internal.

---

## Repository dan aplikasi

Repository:

```text
https://github.com/firdausrakh/delineasi-dta-bbwsso
```

Production web (sesuai repository public release):

```text
https://delineasi-dta-bbwsso.vercel.app
```
