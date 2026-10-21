# USERFLOW — Alur Operasi WebGIS Delineasi DTA

> Berdasarkan pilihan UI dan endpoint pada snapshot. Langkah ini menggambarkan alur umum; teks tombol/posisi komponen dapat berubah, jadi cek `templates/spatial.html` dan `static/js/spatial.js` saat mengubahnya.

## UF-01 — Buka dan jelajahi peta

1. Akses `/` → shell WebGIS dimuat → MapLibre menampilkan peta dan layer.
2. Sesuaikan basemap/batas DAS/jaringan sungai lewat Layer & Tampilan.
3. Cari lokasi melalui input pencarian; pilih hasil untuk mengarahkan peta atau membuka preview lokasi.
4. State alternatif: lokasi tidak ditemukan, jaringan gagal, layer opsional belum tersedia.

## UF-02 — Tambah outlet

1. Pilih mode tambah titik atau gunakan pencarian peta.
2. Pilih posisi → tinjau koordinat/snapping → beri nama dan metadata sungai bila diperlukan.
3. Simpan ke daftar titik. Alternatif: unggah template `.xlsx` melalui dialog upload.
4. Invalid: koordinat di luar batas, file salah/terlalu besar, nama/ID tidak valid, jumlah titik melebihi batas aplikasi.

## UF-03 — Delineasi satu atau banyak DTA

```text
Outlet dipilih → jalankan delineasi → loading
   ├─ sukses → polygon DTA + atribut + daftar hasil
   └─ gagal → pesan masalah (data/snap/topologi/server) → perbaiki input/ulangi
```

- Satu outlet: `POST /api/delineate`.
- Beberapa outlet: `POST /api/delineate-multi`; perubahan/rekonsiliasi dapat memanggil `POST /api/reconcile-results`.
- Edit posisi outlet mengharuskan perhitungan ulang hasil yang terdampak. Hindari mempertahankan analisis lama dengan geometri baru.

## UF-04 — Karakteristik fisik–hidrologi

1. Pilih kartu DTA yang telah selesai.
2. Jalankan analisis karakteristik (`POST /api/characteristics`).
3. Tampilkan ringkasan, nilai teknis, dan layer turunan bila tersedia.
4. Alternatif: indikator yang memerlukan raster tidak tersedia → tampilkan informasi sumber yang kurang.

## UF-05 — Analisis HSS

1. Buka modal Analisis HSS; pilih DTA yang ada.
2. Ambil karakteristik untuk HSS; pilih metode/parameter dan durasi hujan efektif.
3. `POST /api/hss` → tampilkan kurva/parameter, volume dan warnings.
4. Edit parameter → tandai stale → jalankan ulang sebelum ekspor.
5. Hasil Gama I yang relevan dapat ditampilkan sebagai layer audit khusus.

## UF-06 — Model hidrologi

```text
Pilih Model Hidrologi
   ├─ Modular Drainage Area Ratio → ≥2 DTA → unggah debit → donor/target → similarity → simulasi
   ├─ FJ Mock   → data iklim/soil/DEM → parameter GIS/manual/auto → simulasi
   └─ Machine Learning → debit observasi + data fitur → pilih Random Forest/XGBoost → latih/evaluasi → estimasi
```

- Upload workbook debit: `POST /api/hydro-model/workbook`.
- Pratinjau parameter GIS FJ Mock: `POST /api/hydro-model/parameters`.
- Simulasi: `POST /api/hydro-model`.
- Jika input donor, periode atau data pendukung tidak cukup, tampilkan penjelasan; jangan menjalankan output palsu.

## UF-07 — Unduh hasil

1. Buka menu **Unduh Hasil**.
2. Tentukan format `shp`, `gpkg`, `geojson` atau `kml` serta geometri dan layer tambahan.
3. Aktifkan opsi Karakteristik/HSS/Model hanya ketika hasil valid sudah tersedia.
4. `POST /api/download` → browser mengunduh bundle.
5. Kegagalan ekspor harus meninggalkan titik/hasil UI tetap tersedia.

## UF-08 — Viewport sempit dan keyboard

- Pada zoom browser 200% atau perangkat sempit, semua langkah UF-01 s.d. UF-07 tetap dapat dicapai walau panel berpindah atau menjadi scrollable.
- Fokus keyboard dapat mencapai tombol, form, opsi analisis, dialog dan aksi download.
- Peta (konten dua dimensi) boleh menggunakan pan/zoom sendiri; kontrol bukan bagian dari pengecualian ini.

## Catatan integritas alur

Setiap langkah yang memperbarui DTA atau parameter hasil harus menginvalidasi output turunan yang tidak lagi sesuai. `point_id` berfungsi menghubungkan titik, hasil delineasi, analisis, dan unduhan. Implementasi UI aktual harus diuji setelah refactor.
