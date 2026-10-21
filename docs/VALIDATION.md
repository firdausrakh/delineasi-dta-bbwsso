# VALIDATION — Validasi Data, Geometri, dan Hasil

> **Basis:** Pydantic request model, parser workbook, guard perhitungan, dan test snapshot. Ambang yang tidak dicatat di sini wajib dilihat pada implementasi aktif. Jangan mengasumsikan validation domain dan coverage seluruhnya sudah terselesaikan.

## 1. Level validasi

- **BLOCKING** — input salah, dataset wajib kosong, geometri tak bisa dihitung, rumus tidak valid, atau output berisiko keliru. Gagalkan proses dengan pesan yang menjelaskan field/sumber.
- **WARNING** — proses masih menghasilkan hasil, tetapi interpretasi perlu diperiksa (mis. ratio donor/target ekstrem, referensi nested, ekstrapolasi).
- **INFO** — provenance data, asumsi metode, ketersediaan layer, dan keterbatasan cakupan yang tidak menyesatkan.

Kategori di atas adalah kebijakan dokumentasi/review; belum berarti semua handler mengembalikan atribut `severity` terstruktur. Cek respons API aktual.

## 2. Outlet dan request

| Field/kondisi | Guard yang ditemukan |
| --- | --- |
| Longitude/latitude | Rentang `[-180,180]` dan `[-90,90]` pada Pydantic |
| `point_id` | Nonkosong; maksimum 10 karakter |
| `snap_radius_m` | Lebih besar dari 0, maksimum 20.000 m |
| `boundary_match_m` | 10–500 m |
| `paek_tolerance_m` | 10–1.000 m |
| `vw_tolerance_m` | 0–100 m |
| `decimal_separator` | `,` atau `.` |
| Banyak titik | `MAX_POINTS` dari `api/core.py`; jangan tulis angka baru tanpa cek konstanta |
| Upload outlet XLSX | Maksimum 2 MB; header `Nama Titik`, `Nama Sungai`, `Lintang`, `Bujur`; setiap koordinat harus numerik/in range |

Periksa hasil snapping dan lokasi jaringan sungai yang dipilih; validitas angka koordinat saja tidak membuktikan outlet sesuai DAS.

## 3. Geometri/spasial

- Polygon harus nonempty dan valid sebelum perhitungan luas/ekspor; utamakan data proyeksi yang sesuai, bukan derajat langsung.
- Rekonsiliasi nested/bercabang tidak boleh menghilangkan batas bersama atau menciptakan overlap tidak sah.
- Pembatasan *Batas DAS resmi* harus mempertahankan tujuan penetapan batas; bila data acuan tidak ditemukan, tampilkan keterbatasan.
- Perubahan toleransi smoothing/stitching perlu regresi untuk area, shared edge dan kesesuaian outlet.
- Raster opsional tidak boleh diasumsikan ada: pada coverage kurang/invalid laporkan `unavailable` atau kegagalan sesuai metode.

## 4. Karakteristik dan HSS

- Tolak nilai numerik non-finite atau parameter fisik tidak sah untuk metode yang mengharuskan nilai positif.
- `HssRequest.global_tr_hours`: `>0` dan `≤24`.
- Gama I perlu parameter bentuk/geometri yang tersedia; tidak boleh mengisi metrik bentuk sekadar supaya rumus berjalan.
- Audit `Tp/Qp/Tb`, kurva, integral volume, dan equivalent runoff; perubahan parameter wajib membuat hasil lama stale.
- Waktu konsentrasi menggunakan kriteria kesesuaian metode; jangan mengganti status metode menjadi nilai 0 hanya agar grafik selalu lengkap.

## 5. Workbook debit dan model

- Upload debit maksimum 10 MB (ukuran hasil dekompresi workbook juga dibatasi parser); sheet yang invalid memuat alasan.
- `A1 = Tahun`, header bulan dan `I/II`, 24 nilai tengah bulanan per tahun, tahun bilangan bulat dan tidak melebihi tahun berjalan pada parser, tahun tidak boleh duplikat.
- Debit harus numerik, finite, dan tidak negatif. **0 sah**. Data kosong hanya diperbolehkan pada mode/operasi yang mendukung missing secara eksplisit.
- HydroMODAR: ≥2 DTA dan ≥1 referensi debit; set donor/target valid; eksponen `b` >0 ≤3; parameter similaritas wajib tersedia jika diaktifkan.
- RF/XGBoost: membutuhkan observasi sebagai data pelatihan. FJ Mock: parameter mode/kalibrasi, tahun warm-up, data hujan/ET0/DEM/soil harus konsisten; tidak boleh mengarang sumber iklim.
- Band hujan/zonal: cakupan atas **seluruh** DTA diperiksa; hujan negatif, tanggal band salah, dan periode hilang tidak boleh disamakan dengan nol.
- Rasio luas donor/target di luar 0,5–2 dalam HydroMODAR adalah **peringatan pemeriksaan**, bukan otomatis hard-fail.

## 6. Kode status dan tampilan error

`api/core.py` memakai `HTTPException(400)` untuk banyak validasi input; upload oversize dapat memakai `413`, dan request mahal dapat terkena guard antrean. Client harus menampilkan pesan dari API secara aman tanpa menelan sebab. Jangan menjadikan semua error “server error” generik jika detail telah tersedia.

## 7. Quality gate saat mengubah validasi

Cakup valid, invalid, batas minimum/maksimum, missing, zero, outlier, sumber tidak tersedia, dan kemungkinan output lama. Update `docs/CALCULATION.md` + `docs/TESTING.md` dan tes yang mengukur perilaku baru; dokumentasikan penyimpangan dari perilaku terdahulu.
