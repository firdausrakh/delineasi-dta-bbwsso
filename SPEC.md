# SPEC.md — Spesifikasi Ringkas Project

**Produk:** Delineasi DTA BBWS Serayu Opak  
**Status dokumen:** baseline kerja dari snapshot source ZIP yang diaudit, bukan pengganti dokumen perhitungan/PRD.  
**Prinsip:** perbarui hanya ketika scope/invariant berubah dan sudah diverifikasi melalui implementasi, test, atau keputusan resmi.

## 1. Tujuan & pengguna

Aplikasi WebGIS untuk membantu pengguna memilih titik outlet, melakukan delineasi Daerah Tangkapan Air (DTA), mengevaluasi karakteristik fisik/hidrologi, membandingkan hidrograf satuan sintetis (HSS), memproses model hidrologi, serta meninjau/mengunduh hasil. Detail perhitungan, keterbatasan dataset, dan metodologi merujuk ke `docs/TECHNICAL_REFERENCE.md`, kode terkait dan dokumen `docs/CALCULATION.md` / `docs/VALIDATION.md` **bila tersedia**.

## 2. Ruang lingkup yang ada pada snapshot

- **WebGIS:** peta interaktif MapLibre, pemilihan dan penamaan titik outlet, tampilan layer, peta dasar, serta navigasi sidebar/popup.
- **Delineasi:** pemrosesan DTA hulu–hilir dan geometri boundary dengan referensi jaringan hidrologi; ada proses boundary stitching.
- **Karakteristik DTA:** metrik fisik/hidrologi, tampilan analisis, dan keluaran terstruktur.
- **HSS:** metode sintetis yang sudah diimplementasikan, parameter per-DTA, grafik, dan keluaran laporan/spasial.
- **Model hidrologi:** layanan pemodelan hidro, input pendukung, laporan/workbook.
- **Ekspor:** beberapa output analisis/data; format dan detail ditentukan oleh endpoint dan layanan yang benar-benar ada.

**Di luar scope dokumen ini:** menjanjikan akurasi hidrologi, menambah metode, menetapkan SLA, menetapkan tingkat validasi ilmiah, dan mendefinisikan produk baru tanpa persetujuan. Tidak ada fitur baru yang diotorisasi hanya karena dicantumkan di `TODO.md`.

## 3. Arsitektur & struktur teknis

| Area | Source of truth implementasi |
| --- | --- |
| Shell HTTP & static | `api/app.py` |
| API/engine utama | `api/core.py` |
| Layanan analisis | `api/services/` |
| HTML server-rendered | `templates/base.html`, `templates/spatial.html` |
| Design/CSS | `static/css/app.css`, `static/css/ui-components.css`, `static/css/spatial.css`, `static/css/motion.css` |
| JS interaksi & modul | `static/js/common.js`, `static/js/spatial.js`, `static/js/hss.js`, `static/js/hydro-model.js` |
| Unit/integration test | `tests/` |
| Script dataset/R2 | `scripts/` |
| Dependensi/backend deployment | `requirements.txt`, `Dockerfile.vercel`, `vercel.json` |

Framework UI yang digunakan pada snapshot: Jinja2 + CSS + JavaScript, bukan Tailwind/React. GIS memanfaatkan pustaka Python yang dinyatakan di `requirements.txt`. Dataset produksi/runtime didesain untuk Cloudflare R2; jangan menganggap data besar tersedia di repo.

## 4. Invariant dan batasan penting

1. **Ketepatan geospasial:** perubahan perhitungan wajib memeriksa satuan, CRS, batas DAS acuan, konektivitas aliran, dan relasi upstream/downstream sesuai implementasi dan test.
2. **Isolasi DTA:** operasi pada satu DTA tidak boleh tanpa sengaja merusak data, visibilitas, atau konfigurasi DTA lain.
3. **Tidak membuat data palsu:** parameter yang sumbernya tidak ada harus tetap diperlakukan sebagai belum tersedia, bukan diberi hasil rekaan.
4. **Keamanan:** credential/data privat R2 tidak pernah di-bundle sebagai aset publik; jangan mengubah proses upload/deploy tanpa persetujuan.
5. **Performa:** shell awal tetap ringan; engine GIS dimuat terpisah sesuai kebutuhan, perhatikan beban memori dan proses berat.
6. **UI web & zoom:** browser zoom bukan zoom peta; panel kontrol, teks, dialog, form, dan navigasi harus responsif sesuai `docs/UI_DESIGN_RULES.md`, termasuk jika peta itu sendiri tidak direflow seperti dokumen biasa.
7. **Aksesibilitas:** pembesaran teks, fokus keyboard, label kontrol, pesan error dan dark mode tidak boleh rusak oleh perubahan UI.
8. **Kompatibilitas:** jangan mengubah route API, parameter input/output, nama layer, maupun bentuk ekspor tanpa menelusuri konsumen dan regresinya.

## 5. Acceptance criteria untuk perubahan

- **Fitur/logic:** perilaku terdokumentasi, tes area terkait lulus atau batasan uji dinyatakan, tidak ada regresi pada keluaran lama.
- **UI:** hierarki tipografi terlihat, konten terbaca, zoom browser 100–200% berfungsi dan reflow sempit diuji; peta, sidebar, modal, toolbar dan dialog tetap dapat dipakai.
- **Data/deploy:** tidak ada perubahan dataset atau upload otomatis; perubahan skema/manifest memerlukan langkah migrasi dan verifikasi terpisah.
- **Dokumentasi:** hanya memperbarui dokumen yang benar-benar terpengaruh; `README.md` existing tetap menjadi panduan setup.

## 6. Dokumen lain & konflik

- **Inti:** `README.md`, `AGENTS.md`, `TODO.md`.
- **Arsitektur/model data/metode:** `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/CALCULATION.md`.
- **Produk/interaksi:** `docs/PRD.md`, `docs/UI.md`, `docs/UX.md`, `docs/USERFLOW.md`; untuk perubahan UI, `docs/UI_DESIGN_RULES.md` adalah guardrail wajib.
- **Mutu/istilah/keputusan:** `docs/TESTING.md`, `docs/VALIDATION.md`, `docs/DECISIONS.md`, `docs/GLOSSARY.md`.
- **Rujukan detail lama:** `docs/TECHNICAL_REFERENCE.md`; sejarah tidak selalu identik dengan implementasi versi terbaru.
- Semua file di atas tersedia pada paket dokumentasi ini sebagai *baseline as-implemented* snapshot DTA. Dokumentasi SOQ/current meter sengaja tidak disalin.
- Jika dokumen, source, dan tes bertentangan, dokumentasikan bukti serta mintalah klarifikasi sebelum mengubah ketentuan ilmiah/operasional.
