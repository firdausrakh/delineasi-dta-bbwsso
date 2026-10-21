# TESTING — Strategi Pengujian dan Regresi Delineasi DTA

> **Status:** daftar test ditemukan pada snapshot. Dokumen ini **tidak menyatakan test telah dijalankan atau lulus**. Menjalankan test penuh mungkin membutuhkan dependency, raster/vektor, fixture, dan koneksi lingkungan.

## 1. Perintah dasar

```bash
python -m pytest -q
python -m compileall -q api scripts
```

Untuk iterasi cepat, jalankan subset: `python -m pytest -q tests/test_hss_analysis.py`. Pengecekan compile **bukan** substitusi tes fungsi. Jangan upload R2 atau deploy hanya demi pengujian lokal.

## 2. Inventori modul tes snapshot

| File | Cakupan |
| --- | --- |
| `test_boundary_stitch.py` | Snap edge bersama, DTA nested, stitching & geometri sulit |
| `test_characteristics_spatial.py` | Jaringan sungai analisis, main channel, spatial export |
| `test_hydrologic_analysis.py` | Metrik, Tc, kelas respons, fallback lintasan, keamanan report |
| `test_hss_analysis.py` | 7 metode, kalibrasi, konservasi volume, Gama I, benchmark |
| `test_hydro_model.py` | Parser debit, DAR, similarity, donor, R2/model export |
| `test_hydro_rainfall.py` | Raster areal rainfall, coverage, missing band, R2 signature |
| `test_hydro_runoff.py` | FJ Mock neraca air, warm-up, ET0, RF/XGBoost, holdout |
| `test_mock_controls.py` | Prior recession GIS, kalibrasi manual/auto, parameter bounds |
| `test_mock_excel_reference.py` | Replay pembanding workbook/referensi perhitungan Mock |
| `test_performance.py` | Supersede request, antrean heavy jobs |
| `test_shell_performance.py` | Routing shell/static, cache, layer URL, status, UX point name |

## 3. Matriks quality gate per jenis perubahan

| Jika mengubah | Tes otomatis minimum | Tes manual tambahan |
| --- | --- | --- |
| D8/topologi/stitching | `test_boundary_stitch`, test characteristics spatial | Outlet nested, cabang, dekat batas resmi |
| Karakteristik/Tc | `test_hydrologic_analysis`, `test_characteristics_spatial` | Label satuan, indikasi data tidak tersedia, overlay |
| HSS/Gama I | `test_hss_analysis` | Grafik, parameter stale, ekspor tiap metode |
| Donor/HydroMODAR | `test_hydro_model`, `test_hydro_rainfall` | Tahun/period, donor sheet, warning coverage |
| FJ Mock/ML | `test_hydro_runoff`, `test_mock_controls`, `test_mock_excel_reference` | Warmup, donor, hasil parameter, hasil export |
| API/shell/deploy | `test_performance`, `test_shell_performance` | Cold start, error route, map assets |
| Frontend/CSS | tes API terkait + review manual | Desktop/mobile, keyboard, zoom, dialog, map controls |

## 4. Acceptance manual browser zoom/UI

Checklist **wajib untuk modifikasi UI** (pengujian *belum dilakukan* dalam penyusunan dokumen):

- [ ] Zoom 100%, 125%, 150%, 200%: navigasi, modal, layer, tombol analisis dan download dapat digunakan.
- [ ] Viewport setara 320 CSS px atau zoom 400% jika relevan: konten utama reflow; tidak hilang fungsi/informasi.
- [ ] Tidak ada horizontal scroll seluruh halaman yang tidak diperlukan; tabel/grafik/peta 2D boleh mempunyai area sendiri.
- [ ] Ukuran teks berdasarkan role; judul/subjudul/label/value jelas; teks berbahasa Indonesia tidak terpotong.
- [ ] Keyboard Tab, Enter, Esc pada form/dialog; fokus terlihat; error memiliki label yang dapat dibaca.
- [ ] Basemap, layer toggles, snapping popup, upload, analisis dan download masih bekerja.
- [ ] Light/dark contrast, loading, empty/error, stale HSS/model diperiksa.

## 5. Kasus regresi domain yang tidak boleh terlewat

- DTA outlet tunggal vs multipoint/nested; geometri valid, shared edge, dan batas DAS referensi.
- Koordinat negatif, longitude/latitude tertukar, radius snap di luar rentang.
- Data raster/soil/DEM/hujan tidak ada atau cakupannya parsial; tidak mengganti missing dengan nol.
- Hujan 0 sah; band hujan hilang/metadata tidak cocok menyebabkan kegagalan yang jelas.
- HydroMODAR input workbook kosong/invalid, 24 periode/tahun, tahun tidak kontigu, donor overlap dan komputasi volume tahun kabisat.
- HSS Tp/Qp/volume yang dapat dibandingkan fixture dan parameter yang berbeda per DTA.
- Download file per format dengan identitas DTA/satuan benar.

## 6. Pelaporan hasil tes

Gunakan format: tanggal/commit, command, environment & data fixture, `PASS/FAIL/SKIP/NOT RUN`, error dan reproduksi, manual screenshot bila ada. Jangan mengubah checkbox di atas menjadi selesai hanya karena file dokumentasi ini berhasil dibuat.
