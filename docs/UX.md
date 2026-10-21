# UX — Pengalaman Pengguna Delineasi DTA

> **Status:** panduan perilaku dari interface yang tampak pada source, bukan bukti usability study lapangan. Untuk daftar langkah baca `USERFLOW.md`; untuk aturan komponen/zoom baca `UI.md` dan `UI_DESIGN_RULES.md`.

## 1. Prinsip pengalaman

1. **Peta sebagai konteks:** titik/outlet dan polygon DTA selalu dapat dikaitkan secara visual dengan hasil analisis.
2. **Progressive disclosure:** tombol/modal analisis memperlihatkan pengaturan kompleks hanya saat dibutuhkan.
3. **Jangan hilangkan data tidak sengaja:** perubahan titik, koefisien atau metode harus membuat turunan terkait stale/diperbarui secara jelas.
4. **Kesalahan dapat dipulihkan:** input salah diberi pesan spesifik; kegagalan API tidak menghapus semua pekerjaan tanpa alasan.
5. **Provenance terlihat:** hasil GIS dan hidrologi menjelaskan sumber, satuan, cakupan atau ketidaktersediaan input.

## 2. Pencarian dan pemilihan outlet

- Pengguna dapat mencari lokasi atau menentukan outlet dari peta; nama sungai/lokasi membantu orientasi.
- Tampilkan koordinat, hasil snapping dan jarak apabila tersedia; jangan diam-diam menggeser outlet jauh tanpa konfirmasi/informasi.
- Upload `.xlsx` memakai template tersendiri untuk outlet. Kesalahan header, kolom, koordinat atau ukuran file dilaporkan dekat alur upload.
- Pada multipoint, identitas outlet harus konsisten antara kartu, peta, analisis dan ekspor.

## 3. Layer, navigasi dan peta

- Kelompok layer dapat ditampilkan/sembunyikan serta diatur (basemap, batas DAS, jaringan sungai, karakteristik, Gama I).
- Perubahan layer tidak boleh mengubah atau menghilangkan perhitungan DTA yang tersimpan.
- Toggle visibility per DTA tetap independen dari DTA lain.
- Pada keyboard/touch, akses modal dan kontrol harus berfungsi tanpa presisi pointer ekstrem.

## 4. Analisis karakteristik

- Pemilihan DTA harus terlihat; ketika sedang menghitung tampilkan loading dan cegah hasil terdahulu salah diasosiasikan.
- Bagi metrik ke ringkasan dan detail teknis; bedakan ukuran, unit, interpretasi, dan sumber datanya.
- Ketika DEM/asset opsional tidak ada, gunakan status “tidak tersedia” dan penjelasan, bukan mengisi 0.

## 5. HSS

- Pilih DTA dan metode; isi koefisien per metode/DTA; jalankan analisis; baca kurva serta ringkasan Tp/Qp/Tb dan audit volume.
- Setelah input koefisien diubah, berikan status **perlu dihitung ulang** dan cegah ekspor hasil lama.
- Konstruksi geometri Gama I adalah overlay audit opsional; tidak wajib tampil secara default.

## 6. Model hidrologi

- Pilihan Modular Drainage Area Ratio, FJ Mock, atau Machine Learning menjelaskan prasyarat berbeda.
- Donor, range tahun, data input workbook, pilihan parameter, warm-up dan hasil harus jelas saling terkait.
- FJ Mock dapat memakai prior GIS; Machine Learning membutuhkan observasi pelatihan; Modular Drainage Area Ratio mensyaratkan banyak DTA dan donor.
- Warnings dari coverage, ekstrapolasi, keterbatasan validasi dan periode data tidak boleh hilang dari UI.

## 7. Unduhan dan feedback

- Menu download menjelaskan format spasial dan opsi analisis. Opsi yang belum dapat digunakan dinonaktifkan beserta alasan.
- Progress, kegagalan, dan selesai harus dapat dipahami tanpa hanya mengandalkan warna.
- Jaga file hasil sesuai data aktif dan parameter terakhir yang sudah dihitung.

## 8. Aksesibilitas dan zoom

- Pengguna dapat memperbesar browser tanpa kehilangan tombol utama atau hasil analisis.
- Dialog scrollable dan dapat ditutup keyboard. Label panjang berbahasa Indonesia boleh wrap.
- Tampilan light/dark, status fokus, urutan tab dan touch target ditinjau pada perubahan UI.
- Asumsi target WCAG bukan bukti pengujian otomatis: verifikasi terpisah dan dokumentasikan gap.
