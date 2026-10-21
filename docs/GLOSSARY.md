# GLOSSARY — Istilah Delineasi DTA, GIS, dan Hidrologi

> Istilah orientasi yang digunakan dalam project. Definisi operasional numerik tetap mengacu pada fungsi, metadata dataset, dan `CALCULATION.md`.

| Istilah | Penjelasan dalam konteks aplikasi |
| --- | --- |
| DTA | Daerah Tangkapan Air yang berkontribusi aliran menuju outlet tertentu; geometri batas dan luas DTA dihitung dari data topologi/DEM |
| DAS | Daerah Aliran Sungai; batas DAS acuan dipakai sebagai referensi pembatasan geometri |
| Outlet | Titik pelepasan/peninjauan aliran; menjadi lokasi delineasi DTA |
| Snapping | Penyesuaian posisi outlet ke jaringan sungai/cell valid terdekat menurut radius dan prosedur engine |
| Subbasin | Unit tangkapan lebih kecil pada dataset topologi, dapat digabung mengikuti hulu–hilir |
| D8 Flow Direction | Raster arah aliran ke satu dari delapan sel tetangga; dipakai untuk penelusuran catchment lokal |
| Upstream | Bagian jaringan/luas yang terletak di hulu outlet atau link tertentu |
| Downstream | Bagian jaringan/aliran yang menerima kontribusi dari bagian hulu |
| Nested DTA | Satu area tangkapan dapat mencakup area outlet lain pada jaringan yang sama |
| Cumulative area | Seluruh luas yang berkontribusi sampai outlet, termasuk subarea hulu |
| Incremental area | Luas tambahan di antara hubungan outlet dalam hasil multipoint; **bukan** luas penuh untuk skala transfer debit |
| Boundary stitching | Penyesuaian tepi geometri agar DTA bersebelahan/nested tetap konsisten |
| Map zoom | Tingkat perbesaran visual peta MapLibre; berbeda dari zoom browser |
| Browser zoom | Perbesaran konten web yang mengurangi viewport efektif dalam CSS pixels dan menuntut reflow UI |
| CRS | Coordinate Reference System; sistem referensi koordinat untuk posisi/jarak/luas |
| Equal-area projection | Proyeksi yang menjaga hubungan luas, dipakai untuk perhitungan area raster/DTA tertentu |
| DEM | Digital Elevation Model; raster ketinggian untuk analisis topografi dan flowpath |
| Flowpath | Jejak lintasan aliran; digunakan dalam metrik panjang/waktu konsentrasi |
| Drainage density | Kerapatan jaringan sungai terhadap luas DTA sesuai definisi/metrik engine |
| Orde Strahler | Pengurutan cabang jaringan aliran/sungai menurut aturan orde sungai |
| CN | Curve Number untuk perkiraan sifat infiltrasi/limpasan menurut kombinasi input yang dipakai metode |
| Tc | Time of Concentration, waktu konsentrasi; aplikasi membandingkan beberapa metode dan domain kesesuaiannya |
| HSS | Hidrograf Satuan Sintetis; perkiraan respons debit akibat hujan efektif satuan, bukan hasil pengamatan langsung |
| Tp / Qp / Tb | Waktu ke puncak / debit puncak / waktu dasar hidrograf, sesuai metode yang dihitung |
| Gama I | Salah satu metode HSS yang memerlukan parameter geometri serta karakter jaringan DAS |
| AU, WL, WU | Parameter geometrik Gama I: luas bagian hulu dan lebar DTA pada potongan lintasan tertentu |
| HydroMODAR | Modul estimasi transfer debit DTA target berdasarkan luas dan opsional kemiripan karakteristik donor |
| DAR | Drainage Area Ratio, pendekatan skala luas tangkapan untuk transfer debit |
| Donor | DTA referensi dengan catatan debit pengamatan untuk transfer/pelatihan |
| Target | DTA yang akan diestimasi dari model atau transfer donor |
| FJ Mock | Model neraca air untuk estimasi limpasan/debit dengan parameter GIS/manual/kalibrasi |
| RF / XGBoost | Random Forest dan XGBoost; model machine learning pada modul debit yang memerlukan data pelatihan |
| ET0 | Evapotranspirasi referensi yang dipakai sebagai input neraca air |
| Warm-up | Periode awal simulasi untuk membentuk state model sebelum jendela output utama |
| CAT | Cekungan Air Tanah; pada HydroMODAR digunakan sebagai konteks, bukan bobot otomatis |
| SoilGrids | Sumber atribut/raster tanah yang diproses modul model jika data tersedia |
| R2 | Cloudflare R2 object storage untuk dataset runtime privat dan sebagian aset peta publik |
| Stale result | Hasil lama yang tidak lagi selaras dengan titik/geometri/parameter terakhir dan harus dihitung ulang |
| Reflow | Perubahan tata letak otomatis saat ruang viewport menyempit atau teks membesar |

## Aturan istilah

- Gunakan `DTA` untuk unit outlet spesifik dan `DAS` untuk konteks batas yang lebih besar, kecuali sumber/metode mendefinisikan lain.
- Tampilkan angka dan unit jelas: `km²`, `m`, `mm`, `jam`, `m³/det`.
- Gunakan istilah `belum tersedia` atau `tidak valid` untuk input yang kurang; jangan mengganti dengan angka 0.
- Saat mengubah label UI/ekspor, periksa konsistensi nama kolom, satuan, `docs/DATA_MODEL.md`, dan test.
