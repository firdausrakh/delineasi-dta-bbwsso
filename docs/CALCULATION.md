# CALCULATION — Aturan Perhitungan DTA dan Hidrologi

> **Status:** rangkuman *as-implemented* berdasarkan `api/core.py`, `api/services/hydrologic_analysis.py`, `hss_analysis.py`, `hydro_model.py`, `hydro_runoff.py` dan test. **Bukan pengganti kajian/validasi ilmiah atau standar resmi.** Rumus lengkap dan default koefisien setiap metode harus selalu diverifikasi pada fungsi asal sebelum dimodifikasi.

## 1. Konvensi dasar

- Longitude/latitude: derajat geografis; operasi geometri dilakukan di CRS proyeksi yang digunakan engine, jangan langsung menghitung luas dari derajat.
- Luas DTA: km²; panjang/ambang spasial: m atau m²; debit: m³/s (di UI ditampilkan `m³/det`); hujan: mm; durasi HSS: jam.
- Luas equal-area memakai transformasi/proyeksi yang disiapkan engine. `api/core.py` menyediakan `area_km2_equal()` dan ekspor transform geometri.
- Bedakan `0`, `None`, nilai belum tersedia, nilai tidak valid, dan hasil estimasi. Tidak boleh ada imputasi tak terdokumentasi.

## 2. Delineasi dan geometri

1. Pilih jaringan sungai/subbasin berdasarkan outlet dan ambang snapping.
2. Traversal *upstream* dari link outlet memakai `collect_upstream_ids()`; `watershed_union_projected()` menggabungkan geometri subbasin relevan.
3. Alur hybrid pada `hybrid_watershed_projected()` dapat menelusuri catchment lokal raster arah aliran D8 dekat sel outlet.
4. `constrain_to_official()` menerapkan pembatasan Batas DAS acuan; `clean_dta_polygon()` menangani komponen/hole geometri. README source menyebut pembersihan hole lebih kecil dari 62.500 m²; jangan hardcode ulang tanpa mengecek konstanta/konteks pada kode.
5. `reconcile_final_geometries()` menghitung ulang hubungan DTA nested/cabang, overlap, dan area incremental untuk banyak outlet. **Luas kumulatif penuh dan luas incremental berbeda konsep**; analisis debit berbasis luas DTA penuh.

Pengujian geometri terkait ada di `tests/test_boundary_stitch.py` dan `tests/test_characteristics_spatial.py`.

## 3. Karakteristik fisik–hidrologi

`build_hydrologic_analysis()` menyusun berbagai metrik dari geometri dan dataset yang tersedia:

| Kelompok | Indikator yang diproses | Implementasi |
| --- | --- | --- |
| Morfometri | Luas, bentuk, panjang lintasan, sungai utama, sifat geometrik | `hydrologic_analysis.py` |
| Topografi | Elevasi, relief, kemiringan, distribusi kelas, profil | `terrain_metrics()`, `flowpath_metrics()` |
| Jaringan drainase | Orde Strahler, panjang/kerapatan sungai, rasio bifurkasi | `analysis_stream_metrics()`, `drainage_metrics()` |
| Lahan/tanah | Komposisi tutupan lahan, Curve Number, karakteristik sistem lahan | `landcover_metrics()`, `curve_number_metrics()`, `landsystem_metrics()` |
| Respons & Tc | Kelas respons, beberapa formula waktu konsentrasi dan kriteria pemilihan | `hydrologic_response_class()`, `time_of_concentration_metrics()` |

Jika raster opsional tidak tersedia, jangan memunculkan nilai sintetis yang terlihat seperti hasil ukur. Perhitungan `Tc` bukan rerata sederhana semua metode: engine menyaring kesesuaian domain dan membentuk rekomendasi yang harus diaudit terhadap fungsi aktif.

## 4. Hidrograf Satuan Sintetis (HSS)

Tersedia: **NRCS/SCS, Nakayasu, Snyder–Alexeyev, Gama I, Limantara, ITB-1b, ITB-2b**, masing-masing di `api/services/hss_analysis.py` (fungsi `_scs`, `_nakayasu`, `_snyder`, `_gama1`, `_limantara`, `_itb1b`, `_itb2b`).

- Input: `hydrologic_analysis`, metode, parameter per metode, *input overrides*, dan durasi hujan efektif `global_tr_hours` (>0, maksimal 24 jam pada request).
- Output mencakup waktu puncak (`Tp`), debit puncak (`Qp`), waktu dasar (`Tb`) bila relevan, deret ordinat, serta pemeriksaan volume/limpasan ekuivalen.
- `_time_grid()` menyusun ordinat berdasarkan durasi hujan efektif dengan memasukkan titik puncak/akhir penting; `_volume()` mengintegrasikan debit terhadap detik (aturan trapesium).
- Volume limpasan satuan 1 mm pada luas DTA dalam km² setara **1.000 × luas_km² m³** (hubungan dimensional), dipakai sebagai tolok ukur konservasi volume, bukan alasan menormalisasi diam-diam kurva metode.
- Gama I membutuhkan metrik bentuk/geometri tertentu; jangan memaksakan perhitungan saat input wajib tidak ada. Konstruksi spasial AU/WL/WU harus konsisten dengan geometri sumber.
- Perubahan koefisien setelah kalkulasi membuat hasil lama stale; hitung ulang sebelum export.

Perubahan formula/kalibrasi harus diperiksa dengan `tests/test_hss_analysis.py`, termasuk benchmark dan audit volume yang telah ada.

## 5. HydroMODAR: Drainage Area Ratio (DAR)

Dari `api/services/hydro_model.py`, transfer satu donor:

```text
Q_target(t) = Q_donor(t) × (A_target / A_donor)^b
```

`b` default 1 dan harus `0 < b ≤ 3`. Pada beberapa donor, transfer donor dijumlahkan dengan bobot:

```text
D_i = rerata jarak parameter terpilih antara target dan donor i
w_i = exp(-D_i) / Σ exp(-D_j)
Q_target(t) = Σ [w_i × Q_donor_i(t) × (A_target/A_donor_i)^b]
```

Tanpa grup kemiripan, bobot sama. Grup meliputi `aquifer`, `soil`, `landcover`, `terrain`, `rainfall`; CAT dan litologi dicatat sebagai konteks, bukan grup pembobotan. Fungsi `group_distance()` memakai perbedaan proporsi kelas, skala karakteristik fisik, dan jarak hujan `Σ|Ptarget−Pdonor| / Σ(Ptarget+Pdonor)` pada periode sejajar. Metode ini adalah asumsi transfer yang terdokumentasi, **bukan model terkalibrasi otomatis**.

- Donor diselaraskan pada **irisan tahun** bersama, dengan 24 periode tengah bulanan/tahun.
- Debit nol valid; nilai hilang tidak boleh otomatis menjadi nol.
- Akumulasi volume debit menggunakan durasi aktual paruh pertama/kedua bulan (`15` dan `jumlah hari bulan − 15`), termasuk tahun kabisat.
- Analisis statistik mewadahi `Q10`–`Q95` berbasis konvensi `PERCENTILE.EXC`, bukan FDC harian; band sensitivitas donor bukan confidence interval.
- Pertimbangkan rasio luas, kecukupan cakupan parameter, donor nested, peringatan ekstrapolasi, dan validasi antar referensi.

## 6. FJ Mock dan machine learning

- **FJ Mock:** neraca air berbasis masukan hujan/ET0, parameter GIS atau manual, periode pemanasan, dan opsi kalibrasi terhadap debit pengamatan. Implementasi: `hydro_runoff.py`, `hydro_mock_settings.py`, `hydro_soil.py`, `hydro_climate.py`, `hydro_recession.py`. Jangan menganggap parameter dapat diisi nol otomatis saat data tidak ada.
- **Random Forest/XGBoost:** pelatihan dari data debit pengamatan serta fitur hidrometeorologi/spasial; tidak boleh dijalankan tanpa donor observasi. Lihat `simulate_runoff()` dan tes spatial holdout.
- Pilihan durasi tahun, kelengkapan hujan harian, warm-up, metadata ET0, dan cakupan DEM/soil adalah faktor validasi. Bukan semua data snapshot tersedia untuk menjalankan simulasi penuh.

## 7. Aturan perubahan formula

1. Tunjuk fungsi sumber dan fixture pembanding; catat versi perubahan dan satuan.
2. Uji normal, nol, nilai hilang, input di batas, DTA kecil/nested, dan kasus geometri sulit.
3. Verifikasi konsistensi hasil UI, JSON API, XLSX, PDF, dan layer spasial.
4. Jangan mengganti persamaan metode berdasar perkiraan, menyebut keluaran sebagai hasil observasi, atau menghapus guard numerik tanpa persetujuan domain.
5. Perubahan ilmiah wajib memperbarui `docs/VALIDATION.md`, `docs/TESTING.md`, dan decision record.
