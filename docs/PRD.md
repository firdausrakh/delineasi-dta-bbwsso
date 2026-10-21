# PRD — Delineasi DTA BBWS Serayu Opak

> **Dokumen deskriptif dari snapshot yang ada, bukan roadmap fitur baru yang telah disetujui.** Ringkasan kemampuan disusun dari README asli, template UI, API, dan test. Hal di luar snapshot harus diputuskan terpisah.

## 1. Ringkasan produk

Aplikasi WebGIS untuk menentukan batas Daerah Tangkapan Air dari outlet terpilih, menelaah karakteristik fisik–hidrologi, menghitung HSS, melakukan estimasi debit berbasis beberapa pendekatan, dan mengekspor hasil GIS/laporan. Sasaran pengguna yang dituju secara fungsional ialah analis GIS/hidrologi dan staf teknis pengelolaan sumber daya air. Kebutuhan organisasi/role formal belum ditetapkan oleh dokumen ini.

## 2. Masalah yang diselesaikan

- Batas DTA, posisi outlet, serta hubungan hulu–hilir sulit dibandingkan manual tanpa konteks topologi.
- Metrik fisik–hidrologi dan hasil metode perlu konsisten antara peta, laporan, dan data ekspor.
- Beberapa model debit memiliki prasyarat dan risiko interpretasi berbeda yang perlu terlihat jelas, bukan disamarkan dalam satu tombol.
- Data spasial produksi berukuran besar sehingga aplikasi perlu runtime terpisah dari asset source repository.

## 3. Kemampuan produk saat ini

| Modul | Perilaku yang didukung dalam snapshot |
| --- | --- |
| Peta/layer | MapLibre, pencarian lokasi/toponim, jaringan sungai, batas DAS, tema, pengaturan visibilitas |
| Titik outlet | Tambah dari peta/pencarian/unggah Excel, atur nama/sungai, beberapa outlet, pindah atau perbarui |
| Delineasi | DTA hybrid subbasin + D8, snapping, pembatasan DAS, rekonsiliasi topologi multipoint |
| Karakteristik | Morfometri, topografi, drainase, lahan/CN, Tc, laporan/layer turunan jika input tersedia |
| HSS | 7 metode, pengaturan koefisien per DTA, grafik, inspeksi volume, opsi ekspor |
| Model debit | HydroMODAR, FJ Mock, Random Forest/XGBoost dengan prasyarat masing-masing |
| Hasil | Unduhan format spasial `gpkg/shp/geojson/kml`, laporan dan workbook pada opsi yang tersedia |

## 4. Kebutuhan fungsional baseline

- **PRD-01:** pengguna dapat meninjau peta dan memilih outlet dengan koordinat yang valid.
- **PRD-02:** sistem menampilkan hasil DTA yang dapat dikaitkan ke `point_id` dan membedakan cakupan multipoint.
- **PRD-03:** analisis karakteristik tidak mengarang nilai bila sumber raster/vektor tidak ada.
- **PRD-04:** HSS hanya menggunakan parameter yang jelas dan memperingatkan ketika hasil stale; export menuntut hasil terbaru.
- **PRD-05:** model debit memberi pesan tentang donor, periode, observasi, kecukupan data, dan validasi metode.
- **PRD-06:** format ekspor mempertahankan identitas DTA dan satuan.
- **PRD-07:** UI harus usable dengan keyboard dan browser zoom; panel/dialog bisa reflow tanpa menghilangkan kontrol.

## 5. Non-functional baseline

- Performa cold start/analisis dijaga melalui shell ringan, lazy runtime objects dan cache; jangan membuat startup mengekstrak seluruh dataset.
- Credential tetap di server; data besar tidak masuk repo atau response publik tanpa kebutuhan.
- Hasil hidrologi dapat ditelusuri ke data/input/metode yang dipakai.
- Konsistensi UI mengikuti `docs/UI_DESIGN_RULES.md`, bukan ukuran acak `px` dan `font-semibold` di semua tempat.

## 6. Bukan janji produk

Belum ada bukti dalam snapshot tentang autentikasi per pengguna, penyimpanan pekerjaan di server sebagai basis data transaksional, mode mobile offline, atau SLA tertentu. Jangan memasukkannya sebagai fitur eksisting.

## 7. Acceptance / perubahan PRD

Untuk setiap requirement baru, identifikasi UI/endpoint, data minimal, validasi, respons pada kegagalan, ekspor, tes, dan dampak runtime. Perubahan scope harus diselaraskan dengan `SPEC.md`, `docs/USERFLOW.md`, `docs/VALIDATION.md`, dan `docs/DECISIONS.md`.
