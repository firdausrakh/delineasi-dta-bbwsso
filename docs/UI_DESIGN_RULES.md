# UI_DESIGN_RULES.md — Standar UI, Typography & Browser Zoom

**Status:** wajib untuk pekerjaan antarmuka  
**Target:** WebGIS Delineasi DTA BBWS Serayu Opak (Jinja2 + CSS + JavaScript + MapLibre)  
**Ruang lingkup:** `templates/`, `static/css/`, komponen antarmuka di `static/js/`.

> Tujuan: seluruh layar konsisten, hirarki visual mudah dipahami, dan kontrol dapat digunakan saat pengguna memperbesar browser. **Tidak** bertujuan mempertahankan tampilan desktop identik di semua zoom, atau mengubah perilaku zoom/pan peta MapLibre.

## 1. Aturan inti (MUST / SHOULD)

1. **MUST** gunakan semantic typography roles yang konsisten. Bukan ukuran/weight acak per halaman.
2. **MUST** biarkan teks membesar mengikuti browser zoom dan preferensi pengguna; jangan menonaktifkan scaling atau mengunci root font size ke piksel.
3. **MUST** desain layout berdasarkan ruang tersedia: Grid/Flexbox, `minmax()`, `%`, `rem`, `fr`, `max-width`, `clamp()` dan konten yang boleh membungkus (wrap).
4. **MUST** tidak menyembunyikan teks/kontrol penting dengan fixed height, clipping, `text-overflow`, atau `overflow: hidden` tanpa alternatif yang setara.
5. **MUST** mendukung reflow untuk **kontrol** WebGIS (sidebar, toolbar, popup, dialog, kartu, filter, tombol), termasuk ketika viewport efektif menyempit akibat browser zoom.
6. **MUST** membedakan zoom browser (besar UI/viewport CSS) dengan zoom peta (level MapLibre). Jangan mengubah `map.setZoom()` untuk mengatasi browser zoom.
7. **MUST** mempertahankan akses keyboard, visible focus, kontrast, dark mode dan reduced motion.
8. **SHOULD** memodifikasi CSS hanya pada komponen terkait; hindari `!important` baru atau override global jika tidak ada justifikasi.
9. **SHOULD** menerapkan token baru bertahap sesuai modul, karena stylesheet existing memiliki banyak selector spesifik dan rule berbasis `px`.

## 2. Satuan CSS: bukan anti-`px`, melainkan anti rigid layout

| Unit/fungsi | Gunakan untuk | Catatan |
| --- | --- | --- |
| `rem` | font size, spacing, radius, min-width komponen | mengikuti root font size & browser zoom |
| `em` | elemen yang harus mengikuti font elemen sendiri | hati-hati penggandaan nilai pada elemen nested |
| `%` | lebar relatif container | jangan tetapkan fixed width yang melebihi viewport |
| `fr`, `minmax()`, `auto-fit` | kolom grid fleksibel | gunakan `minmax(0, 1fr)` ketika konten dapat panjang |
| `clamp()`, `min()`, `max()` | nilai fleksibel dan batas | untuk font, libatkan `rem` agar tetap accessible |
| `dvh`, `%` | tinggi area interaktif dan modal | lebih aman pada viewport mobile dinamis |
| `px` | border 1px, detail visual, ukuran intrinsik kecil, offset koordinat, CSS breakpoint | **boleh** jika tidak menyebabkan clipping/reflow gagal |

**Larangan praktis:** jangan menetapkan `width: 1000px` untuk halaman, `height: 240px` untuk card berisi teks dinamis, ukuran font mikro untuk sekadar memasukkan semua teks, atau `white-space: nowrap` pada label panjang tanpa fallback. Jangan mengubah `px` pada algoritma/piksel GIS secara mekanis menjadi `rem`.

### Contoh pola container, grid, flex

```css
/* Contoh pola; adopsi selektif agar tidak menimpa CSS produksi. */
.example-container {
  inline-size: min(100% - 2rem, 72rem);
  margin-inline: auto;
}
.example-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 17rem), 1fr));
  gap: 1rem;
}
.example-flex-child {
  min-inline-size: 0; /* izinkan konten panjang mengecil dan wrap */
}
.example-long-label {
  overflow-wrap: anywhere;
}
.example-card {
  min-inline-size: 0;
  block-size: auto; /* bukan height tetap */
}
```

**Jangan terapkan contoh ini secara global** tanpa audit terhadap `static/css/spatial.css` dan layout peta.

## 3. Hierarki tipografi: enam role

**Font existing:** Plus Jakarta Sans, fallback `system-ui, sans-serif`. Pertahankan identitas font, termasuk saat gagal memuat font eksternal. Baseline di bawah adalah target desain untuk UI baru/refactor terencana, **bukan mandat mengganti semua ukuran lama sekaligus**.

| Role | Ukuran token (target) | Weight | Line-height | Kegunaan |
| --- | --- | --- | --- | --- |
| Page title | `clamp(1.75rem, 1.5rem + 1vw, 2rem)` | 700 | 1.2 | judul utama halaman/panel penting |
| Section title | `1.5rem` | 600 | 1.3 | kelompok fungsi/analisis |
| Card title | `1.125rem` | 600 | 1.4 | konten card/panel kecil |
| Body | `1rem` | 400 | 1.5 | paragraf, instruksi, nilai biasa |
| Label / secondary | `0.875rem` | 400–600 | 1.5 | input, metadata sekunder, filter |
| Caption | `0.75rem` | 400 | 1.5 | informasi non-kritis/pendamping |

- Teks **krusial** (instruksi, error, nilai penting, label kontrol) jangan disusutkan menjadi caption demi muat satu baris.
- Caption 0.75rem untuk metadata saja; jika sukar dibaca pada perangkat/zoom tertentu, gunakan minimal `0.875rem`.
- Gunakan `h1` → `h2` → `h3` sesuai semantik, bukan berdasarkan style; satu page title utama pada konteks dokumen bila relevan.
- Jangan membuat seluruh tombol, teks isi, judul, label, dan nilai menjadi bold/semibold. Gunakan **size + weight + color + spacing** untuk memberi penekanan.
- Tidak boleh memisahkan label dari input saat wrap; error message harus terlihat saat konten membesar.
- Pastikan warna teks sekunder tetap cukup kontras di light/dark mode.

### Token yang bisa diperkenalkan ke stylesheet utama

```css
/* Contoh token untuk migrasi bertahap; hindari menduplikasi nama token existing. */
:root {
  --type-page: clamp(1.75rem, 1.5rem + 1vw, 2rem);
  --type-section: 1.5rem;
  --type-card: 1.125rem;
  --type-body: 1rem;
  --type-label: 0.875rem;
  --type-caption: 0.75rem;
  --type-weight-regular: 400;
  --type-weight-semibold: 600;
  --type-weight-bold: 700;
}
.ui-page-title {
  font-size: var(--type-page);
  font-weight: var(--type-weight-bold);
  line-height: 1.2;
}
.ui-section-title {
  font-size: var(--type-section);
  font-weight: var(--type-weight-semibold);
  line-height: 1.3;
}
.ui-card-title {
  font-size: var(--type-card);
  font-weight: var(--type-weight-semibold);
  line-height: 1.4;
}
```

## 4. Spacing, proporsi, dan kepadatan informasi

Gunakan scale `0.25rem`, `0.5rem`, `0.75rem`, `1rem`, `1.5rem`, `2rem`, `3rem`. Contoh: judul→subtitle `0.5rem`; judul section→konten `1rem`; antar-card `1–1.5rem`; antar-section `2–3rem`. Ini **baseline**, bukan pengganti pertimbangan ruang pada panel WebGIS yang padat.

- Satu card sebaiknya satu konsep/tugas utama. Gunakan pemisahan visual dan whitespace, bukan border/warna yang berlebihan.
- Utamakan readable line length untuk paragraf panjang (`max-inline-size` bila memungkinkan), tetapi jangan memotong data numerik, koordinat, satuan atau label peta.
- Data hasil perhitungan harus membedakan **label, nilai, unit, status/keterbatasan** secara konsisten.
- Dalam densitas tinggi, prioritaskan pengelompokan dan progressive disclosure daripada mengecilkan font menjadi 8–10px.

## 5. Browser zoom, reflow, dan CSS breakpoints

**Target uji manual wajib untuk perubahan UI bermakna:** 100%, 125%, 150%, 200% pada desktop, ukuran mobile, serta kondisi setara viewport sempit sekitar 320 CSS px (misalnya 1280 CSS px awal lalu zoom 400%). Kriteria WCAG Reflow 1.4.10 berlaku dengan pengecualian terhadap konten dua dimensi tertentu seperti peta/tabel data; pengecualian **tidak meliputi** label, kontrol peta, sidebar, bantuan, atau dialog.

- Media queries mengacu pada viewport **CSS pixels** efektif; ini wajar. Perubahan zoom dapat memicu breakpoint tanpa perlu event listener zoom khusus.
- Saat ruang tak cukup, ubah dua/lebih kolom ke satu; biarkan tombol wrap, pindahkan atau ringkas kelompok aksi tanpa kehilangan akses.
- Wajib bisa membaca semua teks penting; hindari halaman penuh horizontal scroll. Tabel data atau peta boleh punya area scroll/pan sendiri bila sifat datanya memerlukan dua dimensi.
- Gunakan `min-width:0` pada grid/flex children; `overflow-wrap:anywhere` untuk teks panjang (bukan mengacak kode/koordinat sehingga ambigu).
- Tinggi dialog/panel tidak boleh melebihi ruang tersedia tanpa scroll yang bisa dioperasikan.

```css
.example-analysis-layout {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 1.5rem;
}
@media (max-width: 48rem) {
  .example-analysis-layout { grid-template-columns: minmax(0, 1fr); }
}
.example-dialog {
  inline-size: min(40rem, calc(100% - 2rem));
  max-block-size: calc(100dvh - 2rem);
  overflow: auto;
}
```

## 6. Ketentuan khusus WebGIS/MapLibre

WebGIS menggunakan viewport peta yang memang dapat membutuhkan `position: fixed`, `height: 100%`, lapisan overlay dan `overflow: hidden` pada **kanvas peta**. Jangan mengganti struktur ini secara membabi buta. Namun:

- **Panel samping** harus tetap dapat dibuka/ditutup dan di-scroll sendiri ketika zoom browser naik. Pengguna harus tetap dapat mengakses tindakan utama tanpa elemen tertutup.
- **Dialog dan modal** harus berada dalam viewport efektif, termasuk saat header/browser UI mengurangi tinggi tampilan; body dialog scrollable, tombol close dan aksi primer terjangkau.
- **Popup, legend, attribution, toast, toolbar, control layer** tidak boleh saling tumpang tindih atau terpotong oleh batas viewport; kelompok aksi dapat wrap, collapse, atau pindah posisi yang tepat.
- Saat panel ukuran/visibilitas berubah, jika diperlukan panggil `map.resize()` secara terkontrol untuk memperbaiki ukuran kanvas; jangan sembarang ubah posisi outlet/geometri.
- Jangan memblokir zoom browser dengan meta viewport `user-scalable=no` atau `maximum-scale=1`.
- Event wheel/pinch pada peta dan di dalam panel harus ditinjau agar tidak menghalangi scrolling panel/form.
- **Pisahkan state:** `map zoom` ≠ `browser zoom`, hindari persistensi zoom UI melalui properti zoom peta.

## 7. Aksesibilitas dan interaksi

- Setiap input memiliki label yang terlihat, tombol icon punya accessible name/`aria-label`, dialog dengan heading yang tepat dan mekanisme tutup keyboard.
- Fokus keyboard terlihat; tab order mengikuti urutan logis; konten dinamis penting bisa dipahami tanpa hanya warna.
- Perhatikan kontras WCAG AA: teks normal 4.5:1, teks besar 3:1; kontrol non-text penting 3:1 jika relevan.
- Ukuran target pointer minimal menurut WCAG 2.2 AA 24×24 CSS px atau memenuhi pengecualiannya; target nyaman di perangkat sentuh dianjurkan sekitar 44×44 CSS px jika ruang memungkinkan.
- Hormati `prefers-reduced-motion` yang sudah dipakai di `static/css/motion.css`.
- Uji dengan label Indonesia panjang, nilai numerik besar, error validasi, dan tooltip yang tidak sekadar muncul pada hover.
- Jangan gunakan `transform: scale()` atau CSS `zoom` untuk mengecilkan seluruh aplikasi sebagai solusi browser zoom.

## 8. Cara implementasi di repo ini

1. Cari rule existing dari `static/css/app.css`, `static/css/ui-components.css`, `static/css/spatial.css`, `static/css/motion.css` dan urutan stylesheet yang disisipkan `templates/base.html` dan `templates/spatial.html`.
2. Jika token global belum tersedia, usulkan lokasi token yang jelas pada CSS yang telah ada; tidak perlu membuat file CSS tambahan setiap tugas.
3. Migrasikan komponen yang disentuh ke role typography/spacing semantik. Jangan refactor seluruh 5k+ baris `spatial.css` hanya untuk satu dialog.
4. Gunakan `rem`/fleksibilitas pada layout UI; **jangan** mengubah konstanta JS terkait koordinat, peta, hit-test, raster, DPI/canvas, atau format data dengan pencarian-ganti `px`.
5. Audit mobile, desktop, zoom, dark mode, dan interaction regression sebelum mengklaim selesai.
6. Jika ada `docs/UI.md` pada workspace pengguna, pertahankan sebagai rincian visual; tautkan ke dokumen ini alih-alih menduplikasi aturan.

## 9. Checklist QA / Definition of Done

- [ ] Page title / section / card / body / label / caption dibedakan dengan jelas dan konsisten.
- [ ] Tidak ada teks penting yang dipaksa 8–10px demi menghemat ruang atau hanya dijadikan ikon tanpa label accessible.
- [ ] Zoom browser 100%, 125%, 150%, 200% diuji pada area UI yang berubah.
- [ ] Reflow viewport efektif sekitar 320 CSS px / zoom tinggi diuji; bila gagal, hambatan terdokumentasi (kecuali peta/tabel dua dimensi).
- [ ] Sidebar, navbar, toolbar, form, dialog, dropdown, legenda, toast dapat diakses tanpa clipping.
- [ ] Tidak ada horizontal overflow halaman yang tidak diperlukan; scrollbar lokal hanya untuk area data/peta yang membutuhkannya.
- [ ] Panning, zoom MapLibre, layer, outlet, analisis, dan export yang terdampak tidak rusak.
- [ ] Navigasi keyboard, visible focus, contrast, dark mode dan reduced motion diperiksa.
- [ ] Hasil pemeriksaan yang **benar-benar dilakukan** dicatat; item yang belum dijalankan ditulis eksplisit sebagai pending.

**Catatan:** dokumen ini adalah standar pengembangan, bukan bukti aplikasi existing sudah memenuhi checklist.
