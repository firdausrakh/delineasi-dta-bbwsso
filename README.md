# Delineasi DTA — BBWS Serayu Opak

**Delineasi DTA** adalah aplikasi **WebGIS** untuk memilih outlet, melakukan delineasi *Daerah Tangkapan Air* (DTA), menganalisis karakteristik fisik–hidrologi, menghitung Hidrograf Satuan Sintetis (HSS), menjalankan model hidrologi, serta meninjau dan mengunduh hasil.

- **Versi aplikasi:** `1.4.0` (diverifikasi dari `api/core.py` pada snapshot ZIP).
- **Stack:** Python, FastAPI, GeoPandas, Shapely, Rasterio, HTML/Jinja2, CSS, JavaScript, MapLibre.
- **Runtime produksi:** Vercel Container; data runtime privat di Cloudflare R2 dan *map assets* publik disajikan melalui rute `/geodata/*`.
- **Dataset produksi yang terdokumentasi:** `HYDRO_DATASET=1km2`.
- **Pendekatan data:** dataset hidrologi *predefined/read-only*; data sumber besar dan kredensial tidak disimpan di repository.

> **Mulai dari sini.** `README.md` adalah orientasi dan panduan singkat. Ketentuan teknis rinci dari README lama dipertahankan di [`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md), termasuk prosedur R2, runtime, metode, dan histori. Sebagian bagian referensi adalah catatan historis dan harus diverifikasi terhadap kode aktif sebelum dipakai untuk perubahan perilaku.

## Struktur Dokumentasi

```text
/
├── AGENTS.md
├── README.md
├── SPEC.md
├── TODO.md
└── docs/
    ├── ARCHITECTURE.md
    ├── DATA_MODEL.md
    ├── CALCULATION.md
    ├── PRD.md
    ├── UI.md
    ├── UX.md
    ├── USERFLOW.md
    ├── TESTING.md
    ├── VALIDATION.md
    ├── DECISIONS.md
    ├── GLOSSARY.md
    ├── UI_DESIGN_RULES.md
    └── TECHNICAL_REFERENCE.md
```

**Seluruh file di atas tersedia secara fisik pada paket ini.** Sebelas dokumen domain disusun sebagai *baseline as-implemented* dari snapshot source Delineasi DTA yang diunggah, **bukan** salinan dokumen SOQ. Dokumen baru perlu ditinjau ulang terhadap checkout terbaru jika source lokal sudah berubah. Dokumentasi lama yang tidak ikut ZIP tidak ditimpa atau dihapus.

## Fungsi Dokumen

| Dokumen | Fungsi |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Instruksi coding agent dan ketentuan verifikasi. |
| [`SPEC.md`](SPEC.md) | Batas produk dan invariant sistem. |
| [`TODO.md`](TODO.md) | Backlog serta pemeriksaan yang masih perlu dilakukan. |
| [`docs/PRD.md`](docs/PRD.md) | Produk, kebutuhan, ruang lingkup, dan acceptance baseline. |
| [`docs/UX.md`](docs/UX.md) | Pengalaman dan prinsip interaksi pengguna. |
| [`docs/USERFLOW.md`](docs/USERFLOW.md) | Langkah pengguna dari outlet hingga analisis/unduhan. |
| [`docs/UI.md`](docs/UI.md) | Komponen antarmuka dan kontrak state. |
| [`docs/UI_DESIGN_RULES.md`](docs/UI_DESIGN_RULES.md) | **Wajib:** typography hierarchy, layout fluid, browser zoom, reflow, aksesibilitas WebGIS. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Komponen, backend/frontend, API, sumber data dan deployment. |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) | Bentuk request, relasi outlet/DTA, data spasial, hasil dan satuan. |
| [`docs/CALCULATION.md`](docs/CALCULATION.md) | Alur hitung geometri, karakteristik, HSS, DAR, Mock dan ML. |
| [`docs/VALIDATION.md`](docs/VALIDATION.md) | Guard input, geometri, sumber data dan hasil. |
| [`docs/TESTING.md`](docs/TESTING.md) | Peta test/regresi dan checklist UI/zoom. |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Baseline keputusan teramati, status dan template ADR. |
| [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | Istilah GIS dan hidrologi yang digunakan proyek. |
| [`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md) | Salinan referensi teknis README asli, termasuk R2, deployment dan histori. |

## Urutan Membaca untuk Developer / Coding Agent

1. **Selalu:** `AGENTS.md` → `SPEC.md` → `README.md`; cek `TODO.md` untuk pekerjaan aktif.
2. **Fitur/alur:** `docs/PRD.md` → `docs/UX.md` → `docs/USERFLOW.md`.
3. **UI:** `docs/UI_DESIGN_RULES.md` → `docs/UI.md`; verifikasi template, CSS/JS, dark mode, zoom 100–200%, dan reflow 320 CSS px.
4. **API/data:** `docs/ARCHITECTURE.md` → `docs/DATA_MODEL.md` → source dan test terkait.
5. **Perhitungan hidrologi/geometri:** `docs/CALCULATION.md` → `docs/VALIDATION.md` → `docs/TESTING.md` → implementasi.
6. **Istilah/keputusan/operasional:** `docs/GLOSSARY.md`, `docs/DECISIONS.md`, `docs/TECHNICAL_REFERENCE.md` sesuai tugas.

Jika dokumen berbeda dari source terbaru, catat gap dan verifikasi sebelum mengubah perilaku. Jangan menganggap seluruh hasil ilmiah atau browser zoom sudah diverifikasi hanya karena dokumentasi telah dibuat.

## Baseline Produk

- Peta interaktif dan kontrol layer berbasis MapLibre, dengan dukungan tema dan tampilan perangkat berbeda.
- Outlet dapat dipilih/dicari lalu diproses melalui alur delineasi DTA; tersedia pengaturan titik dan peninjauan hasil.
- Delineasi berbasis subbasin dan raster arah aliran D8, termasuk penanganan koneksi hulu–hilir serta batas DAS acuan.
- Karakteristik DTA mencakup metrik morfometri, jaringan drainase, topografi, dan parameter hidrologi sesuai ketersediaan dataset.
- Metode HSS yang terdokumentasi: NRCS/SCS, Nakayasu, Snyder–Alexeyev, Gama I, Limantara, ITB-1b, ITB-2b.
- Model hidrologi yang tersedia pada snapshot: Modular Drainage Area Ratio, FJ Mock, dan Machine Learning; masing-masing mempunyai prasyarat input dan batas validasi.
- Hasil dapat ditampilkan dan diekspor sesuai modul yang digunakan; beberapa analisis membutuhkan data spasial tambahan yang tidak dibundel dalam ZIP.
- Data spasial dan aset peta produksi berada di R2; perhitungan geometri dan analisis tetap dilakukan pada backend Python.

Detail algoritma, batas validasi, format hasil, dan caveat ilmiah: [`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md) dan implementasi terkait.

## Lingkup dan Batasan Penting

- **Zoom peta berbeda dari browser zoom.** Browser zoom hingga 200% serta *reflow* pada lebar viewport sempit harus diuji untuk panel, form, kontrol, dialog, dan navigasi. Peta adalah kanvas 2D dengan kebutuhan interaksi tersendiri. Baca [`docs/UI_DESIGN_RULES.md`](docs/UI_DESIGN_RULES.md).
- **Tidak semua data tersedia di repository.** Data master lokal, bundle runtime R2, credential, dan file raster/GeoPackage besar disiapkan terpisah.
- **Jangan mengasumsikan hasil model tervalidasi untuk semua data.** Metode tertentu memerlukan input, kalibrasi, pemeriksaan satuan, dan pengujian sesuai sumber data.
- **Jangan melakukan upload R2, migrasi dataset, atau deploy tanpa persetujuan.** Langkah operasional di referensi teknis adalah petunjuk, bukan izin mengeksekusi.
- **Bukan React/Tailwind:** perubahan UI harus menggunakan struktur frontend yang ada kecuali ada keputusan eksplisit mengganti teknologi.

## Menjalankan Aplikasi Secara Lokal

### Prasyarat

- Python dan dependency dari `requirements.txt`; environment Python virtual disarankan. Skrip Windows mencoba Python 3.12 terlebih dahulu, sedangkan Linux/macOS memakai `python3`.
- Salin `.env.example` ke `.env` dan atur backend data. **Jangan commit `.env`.**
- Jika menggunakan `DATA_BACKEND=local`, folder data master yang sesuai harus tersedia di `data/` atau `LOCAL_DATA_DIR`. Jika `DATA_BACKEND=r2`, diperlukan konfigurasi dan izin akses R2 yang sah.

### Pilihan A — Dataset lokal

Isi konfigurasi dasar dalam `.env`:

```dotenv
DATA_BACKEND=local
HYDRO_DATASET=1km2
LOCAL_DATA_DIR=
```

Jalankan dari root repository:

```powershell
# Windows
.\run.bat
```

```bash
# Linux / macOS
./run_linux_mac.sh
```

Kemudian buka `http://127.0.0.1:8000/` dan periksa `http://127.0.0.1:8000/api/info`.

### Pilihan B — Membaca Cloudflare R2

Atur `DATA_BACKEND=r2` serta variable R2 yang relevan pada `.env` berdasarkan `.env.example`. Kunci rahasia harus disimpan pada environment server/lokal yang aman, bukan di frontend. Gunakan peluncur yang sama seperti di atas.

**Referensi konfigurasi lengkap**, termasuk pembuatan bucket, manifest, cache, dan workflow upload, terdapat di [`docs/TECHNICAL_REFERENCE.md`](docs/TECHNICAL_REFERENCE.md).

## Struktur Kode Penting

```text
api/
├── app.py                  # Shell FastAPI / halaman cepat
├── core.py                 # Engine/API hidrologi utama
└── services/               # Geometri, HSS, karakteristik, model, ekspor

templates/                  # HTML/Jinja2
static/css/                 # app.css, ui-components.css, spatial.css, motion.css
static/js/                  # Interaksi peta dan modul analisis
scripts/                    # Pengolahan dataset dan administrasi R2
tests/                      # Unit dan regresi Python
Dockerfile.vercel           # Container deployment
vercel.json                 # Routing/deploy dan map assets
.env.example                # Template konfigurasi (tanpa credential asli)
```

## Pengujian dan Verifikasi

Dari environment Python yang sudah memiliki kebutuhan test (termasuk `pytest`):

```bash
python -m pytest -q tests
```

Tes ini memerlukan dependency/fixture terkait dan **tidak menggantikan pengujian UI manual**. Jika ada kegagalan karena data master/test fixture tidak tersedia, dokumentasikan alasan serta kasus yang belum diuji.

Untuk perubahan UI, periksa minimal: hierarki font, teks yang membungkus, sidebar, popup/modal, akses keyboard, dark mode, dan browser zoom **100%, 125%, 150%, 200%**; untuk perubahan layout besar, periksa juga reflow sekitar **320 CSS px**. Pertahankan navigasi, panning, dan zoom pada MapLibre.

## Perubahan Kode, Dataset, dan Deploy

- **Hanya kode atau UI:** verifikasi dan commit perubahan; deployment mengikuti konfigurasi CI/Vercel yang berlaku. Tidak perlu mengunggah ulang dataset R2 hanya karena CSS/JS berubah.
- **Perubahan dataset:** ikuti prosedur ekspor → unggah → verifikasi di referensi teknis, tetapi hanya setelah otorisasi dan pemeriksaan integritas/checksum serta dampaknya pada hasil hidrologi.
- **Sesudah deploy:** periksa `/api/info`, loading map assets, pencarian outlet, delineasi, analisis, ekspor, dan kegagalan runtime/console.

## Keamanan dan Ketepatan Perhitungan

- Jangan commit `.env`, token Cloudflare, file sumber data privat, atau data pengguna.
- Runtime bucket R2 harus privat; aset peta publik hanya berisi data yang disetujui untuk publikasi.
- Jangan mengubah parameter, algoritma hidrologi, CRS, ataupun satuan berdasarkan dugaan.
- Semua perbedaan nilai analisis atau revisi algoritma harus memiliki pengujian regresi dan catatan keputusan.

## Status Dokumentasi

Dokumen domain `ARCHITECTURE`, `DATA_MODEL`, `CALCULATION`, `PRD`, `UI`, `UX`, `USERFLOW`, `TESTING`, `VALIDATION`, `DECISIONS`, dan `GLOSSARY` **sudah disertakan** pada paket ini. Semua disusun dari source Delineasi DTA snapshot yang disediakan, dan **belum menggantikan review dokumen lama di checkout lokal** jika ada perbedaan versi. Untuk bagian hidrologi/formula, source dan fixture tetap harus ditinjau sebelum menjadikan narasi sebagai standar formal.

`docs/FLOWTRACKER2_MAPPING.md` tidak dibuat karena merupakan dokumen yang muncul pada project SOQ (domain berbeda). Dokumen audit historis juga tidak dimasukkan tanpa bukti kegunaannya untuk DTA.

Versi aplikasi pada snapshot `api/core.py` adalah `1.4.0`. Jika repository telah berkembang setelah snapshot ini, sinkronkan dokumen dengan kode sebelum rilis.
