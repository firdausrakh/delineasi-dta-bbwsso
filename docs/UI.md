# UI — Kontrak Antarmuka WebGIS Delineasi DTA

> **Berbasis:** `templates/base.html`, `templates/spatial.html`, `static/css/*.css`, `static/js/*.js` pada snapshot. Dokumen ini memetakan komponen aktual. **Seluruh aturan typography, satuan relatif, browser zoom, dan aksesibilitas mengacu wajib ke [`UI_DESIGN_RULES.md`](UI_DESIGN_RULES.md)**; jika gaya lama bertentangan, laporkan lalu migrasikan secara bertahap.

## 1. Karakter visual

- Aplikasi berpusat pada kanvas peta MapLibre dan overlay kontrol. Pengguna harus dapat membaca status titik/DTA sambil mempertahankan konteks lokasi.
- `templates/base.html` menetapkan bahasa `id`, font **Plus Jakarta Sans**, elemen header kelembagaan, light/dark theme melalui `data-theme`, dan CSS `app.css`, `ui-components.css`, `motion.css`.
- `templates/spatial.html` menampilkan panel, layer selector, tombol analisis, modal, form upload, dan modal download; `static/css/spatial.css` menangani layout spesifik WebGIS.
- Jangan membuat tampilan ulang dari nol atau menambahkan Tailwind/React hanya agar terlihat serupa dengan contoh desain.

## 2. Bagian interface yang sudah ada

| Bagian | Bukti di source | Fungsi |
| --- | --- | --- |
| Header | `#appHeader`, `#headerHandle`, `#themeToggleBtn` | Brand, navigasi, theme, bantuan/metodologi |
| Map | Konstruktor `maplibregl.Map` di `static/js/spatial.js` | Peta dasar, layer, outlet, geometri DTA |
| Layers | `#basemapModal`, `#showBasins`, `#showRivers`, layer Karakteristik/HSS | Basemap, visibilitas, label, warna, atribut layer |
| Upload | `#xlsxUploadTitle`, endpoint `/api/points-xlsx` | Input outlet lewat workbook |
| Karakteristik | `#hydrologicAnalysisModal`, `#hydrologicAnalysisContent` | Detail metrik/interpretasi |
| HSS | `#hssAnalysisModal`, `#hssDtaSelect` | Pemilihan DTA, parameter, output metode |
| Model | `#hydroModelModal`, panel `#hydroModarPanel`, `#hydroMockPanel`, `#hydroMlPanel` | Donor, model, parameter, simulasi |
| Download | `#downloadModal`, `#downloadAnalysisReport`, `#downloadHss`, `#downloadHydroModel` | Memilih format/analisis dan mengunduh |

Identitas DOM/kelas aktual harus diperiksa sebelum refactor; jangan mengganti `id` yang digunakan JS tanpa memperbarui konsumen.

## 3. Typography hierarchy wajib

Gunakan **role** berikut, bukan memilih ukuran untuk setiap tombol/card secara bebas:

| Role | Ukuran awal (`rem`) | Berat awal | Penggunaan |
| --- | --- | --- | --- |
| Page title | `clamp(1.75rem, 1.5rem + 1vw, 2rem)` | 700 | Judul layar / dialog utama |
| Section title | `1.5rem` | 600 | Kelompok analisis besar |
| Card title | `1.125rem` | 600 | Kartu DTA atau subkelompok |
| Body | `1rem` | 400 | Instruksi, informasi penting |
| Label/secondary | `0.875rem` | 400–600 | Label form, metadata sekunder |
| Caption | `0.75rem` | 400 | Metadata tak kritis; naikkan bila sulit terbaca |

Line-height heading 1.2–1.4, body 1.5; utamakan pembeda hierarki melalui size, weight, warna, dan whitespace. Hindari bold di semua teks. `h1/h2/h3` mengikuti semantik, bukan style. Detail dan token contoh ada di `UI_DESIGN_RULES.md`.

## 4. Spacing dan dimensi

- Gunakan skala `0.25/0.5/0.75/1/1.5/2/3rem`, komponen fleksibel `max-width`, `%`, Grid/Flex, `fr`, `minmax()`.
- `px` boleh untuk border, garis, canvas grafis, atau kasus ukur tertentu; **hindari** fixed widths/heights untuk card, sidebar dan dialog ketika isinya harus membesar.
- `min-width: 0` untuk anak flex/grid, `overflow-wrap` untuk label panjang, area scroll internal yang tetap dapat dioperasikan.
- Untuk tabel/hidrograf, area grafik/tabel boleh scroll sendiri sebagai konten 2D; instruksi/kontrol di sekelilingnya tetap harus reflow.

## 5. State komponen

Komponen aksi wajib membedakan: **idle**, **hover/focus**, **loading**, **success**, **empty/no-data**, **warning/invalid**, **error**, **disabled**, dan **stale result** bila terkait HSS/model. `aria-live` telah digunakan pada beberapa status (`#downloadSummary`, `#hydroStatus`, dan sebagainya); jangan menghilangkannya saat desain ulang.

- Error harus mendeskripsikan penyebab dan tindakan berikutnya.
- Loading analisis tidak boleh menampilkan hasil DTA sebelumnya seolah milik DTA aktif.
- Pilihan unduhan analisis yang belum dijalankan harus nonaktif dengan penjelasan.
- Theme light/dark tetap memberi kontras yang layak pada teks sekunder, fokus, tabel, dan layer control.

## 6. Responsif dan browser zoom

Uji browser zoom **100%, 125%, 150%, 200%**, serta reflow viewport setara **320 CSS px** bila sesuai. Saat ruang menyempit, toolbar wrap/berpindah, grid menjadi satu kolom, kontrol map tidak menimpa form, dan dialog mempunyai `max-block-size` serta internal scrolling. Jangan memakai `transform: scale()` atau menonaktifkan browser zoom untuk “memperbaiki” layout.

**Map zoom ≠ browser zoom.** Peta merupakan kanvas 2D; pengecualian reflow untuk kanvas tidak mencakup tombol map, legend, sidebar, popover, dan modal.

## 7. Kriteria review UI

- Tidak ada elemen saling tumpang tindih, konten penting terpotong, kontrol tidak dapat diakses, atau scroll halaman horizontal tanpa alasan.
- Semantik heading dan label jelas; semua state pembacaan mudah dibedakan.
- Basemap, layer toggle, outlet, modal, analisis, unduhan berfungsi setelah perubahan CSS/markup.
- Tes visual manual belum dapat dianggap lulus hanya dari pemeriksaan teks/CSS; hasil pengujian dicatat di `TESTING.md` atau laporan pekerjaan.
