# DATA_MODEL — Model Data Delineasi DTA

> **Basis:** Pydantic request model `api/core.py`, fungsi pengolahan data, dan `api/services/hydro_model.py`. Aplikasi ini bukan aplikasi CRUD/database transaksi konvensional: data titik/hasil kerja mengalir melalui state klien dan payload API, sementara geodata utama merupakan dataset runtime read-only.

## 1. Domain tree

```text
Dataset runtime (streams, subbasins, D8, DEM, land cover, rainfall, soil, ...)
  └─ OutletPoint (satu outlet)
      └─ DTA result (geometri hasil + atribut + link upstream)
          ├─ Karakteristik hidrologi (metrics, narasi, layer turunan)
          ├─ HSS result (metode, parameter, ordinat, volume)
          └─ Model hidrologi (donor/target, periode, series debit)
               └─ Download bundle (spasial + laporan opsional)
```

## 2. Model request sumber kebenaran

| Pydantic model | Field inti | Penggunaan |
| --- | --- | --- |
| `OutletPoint` | `point_id` string 1–10, `lon` [-180,180], `lat` [-90,90], `source`, `label`, `river_name` | Identitas outlet dan koordinat geodetik |
| `DelineateRequest` | `lon`, `lat`, `snap_radius_m`, `boundary_match_m`, `paek_tolerance_m`, `vw_tolerance_m`, `decimal_separator` | Satu outlet |
| `MultiDelineateRequest` | `points[]` + parameter snapping/stitching/penyederhanaan | Banyak outlet |
| `CachedResultsRequest` | `results[]` | Rekonsiliasi hasil yang sudah dihitung |
| `CharacteristicAnalysisRequest` | `point_result`, `decimal_separator` | Analisis fisik–hidrologi |
| `HssRequest` | `point_id`, `label`, `hydrologic_analysis`, `methods`, `parameters`, `input_overrides`, `global_tr_hours` | Per DTA, per metode |
| `HydroDonor` | `point_id`, `sheet`, `records[]` | Referensi debit |
| `HydroModelRequest` | `points`, `donors`, `model`, rentang tahun, kalibrasi, parameter FJ Mock, grup similarity, dan opsi data | Simulasi |
| `DownloadRequest` | `points`, `geometry_modes`, `formats`, include flags, `hss_results`, `hydro_model` | Paket hasil |

**Jangan mengubah tipe/rentang field hanya berdasarkan tabel ini.** Detail maksimum berasal dari `Field(...)`, `MAX_POINTS`, dan validasi lanjutan pada implementasi aktual.

## 3. Kontrak satuan dan koordinat

- `lon` / `lat` adalah koordinat geografis dalam derajat. Proyeksi digunakan secara internal untuk operasi jarak/luas dan perhitungan GIS; cek transform pada `api/core.py`.
- `area_km2` memakai km²; nilai panjang/jarak berakhiran `_m` menggunakan meter, kecuali dinyatakan lain dalam hasil.
- Debit pengamatan dan output HydroMODAR menggunakan `m³/det`; setiap `record` debit memiliki `year` dan `values` sepanjang **24 periode tengah bulanan**.
- HSS menyimpan waktu/parameter hidrograf, parameter tiap metode, dan ordinat; bentuk tepat respons `calculate_hss()` harus diperiksa sebelum digunakan di pihak ketiga.
- Jangan mengganti nilai `null`/tidak tersedia menjadi nol. Nol debit adalah pengamatan yang valid, sementara nilai hilang memiliki arti berbeda.

## 4. Workbook debit sebagai input

`POST /api/hydro-model/workbook` menerima `.xlsx` maksimum 10 MB. Parser menelusuri relasi sheet workbook, memeriksa `A1 = Tahun`, urutan 12 bulan, serta kolom `I`/`II` untuk masing-masing bulan (B:Y). `validate_records()` menolak tahun/periode ganda dan nilai debit negatif/tidak finite. Pada mode tertentu data hilang boleh diwakili `None` untuk observasi, tetapi tidak otomatis diimputasi.

`POST /api/points-xlsx` menerima template outlet dengan header `Nama Titik`, `Nama Sungai`, `Lintang`, `Bujur`; batas upload terpisah: 2 MB. Jangan menyamakan dua format Excel ini.

## 5. State frontend dan identitas

- `static/js/spatial.js` menyimpan kumpulan `points`, status panel, dan hasil (lihat pemulihan `restoredState.points` serta fitur rekonsiliasi).
- `point_id` menghubungkan hasil delineasi, karakteristik, HSS, model, layer, dan export. Tetap stabil selama satu sesi kerja.
- Setiap operasi yang mengubah outlet/geometri/koefisien harus membatalkan atau memperbarui hasil turunan yang menjadi stale; fitur HSS menerapkan penguncian ekspor hasil lama setelah parameter berubah.
- State browser bukan database otoritatif untuk geodata induk. Jangan menjanjikan persistensi permanen tanpa menelusuri kontrak penyimpanan aktual.

## 6. Data sumber spasial

Sumber termasuk jaringan sungai, subbasin, raster D8 flow direction, batas DAS, DEM/flow length, soil/land cover, dan seri hujan bila tersedia. Sumber tersedia sebagai data lokal dan/atau manifest object R2; *map asset* publik terpisah dari runtime privat. Lihat `docs/TECHNICAL_REFERENCE.md` dan `scripts/` untuk kontrak file/dataset; nama berkas master dapat berbeda dari key runtime.

## 7. Aturan kompatibilitas

1. Untuk perubahan payload, cek model Pydantic → fungsi pembentuk hasil → JS konsumen → test → format export.
2. Jangan mengubah penamaan kolom Excel tanpa migrasi template serta parser dan test.
3. Laporkan CRS, sumber, validitas geometri, satuan, cakupan data, nilai hilang, dan status metode dalam output yang mengandung analisis.
4. Tidak ada definisi schema SQL relasional resmi pada snapshot ini; **jangan mengarang ERD/tabel SQL**.
