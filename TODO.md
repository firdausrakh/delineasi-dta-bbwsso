# TODO.md — Backlog Aktif & Verifikasi

> Ini **backlog awal hasil inspeksi statis ZIP**, bukan daftar bug yang sudah terbukti di browser. Urutan prioritas dapat berubah setelah tes nyata. Tandai `[x]` hanya setelah ada bukti dan catat hasilnya. Jangan menjadikan ide UI sebagai izin refactor masif.

## P0 — Dokumentasi dan keamanan perubahan

- [ ] **Konfirmasi docs aktual yang tidak masuk ZIP.** `docs/` dalam ZIP Delineasi DTA kosong. Screenshot dan `soq.zip` merupakan project SOQ; jangan menganggap file domain di sana sudah ada atau sesuai untuk DTA. Periksa checkout DTA lokal sebelum menggabungkan, memindah, atau menghapus dokumen.
- [ ] **Peta referensi dokumen lama.** Cari link/pemanggilan file Markdown di `README.md`, `docs/TECHNICAL_REFERENCE.md`, `docs/`, scripts, dan konfigurasi agent. Tandai aktif/riwayat/duplikat setelah membaca kontennya.
- [ ] **Review dan cocokkan dokumen domain baru dengan checkout DTA aktual.** Paket ini sudah menyertakan draft dokumen domain untuk diuji, pertahankan `ARCHITECTURE.md`, `DATA_MODEL.md`, `CALCULATION.md`, `TESTING.md`, `VALIDATION.md`, `DECISIONS.md`; review kesesuaian `PRD.md`, `UI.md`, `UX.md`, `USERFLOW.md` dan relevansi `GLOSSARY.md`. `FLOWTRACKER2_MAPPING.md` adalah kandidat arsip **hanya jika ditemukan dan terkait di DTA**; jangan impor dokumen SOQ.

## P1 — Kualitas UI (setelah snapshot baseline visual)

- [x] **Audit typography di `static/css/spatial.css` dan `static/css/ui-components.css`.** Audit 2026-10-21 menemukan teks konten/modal terlalu kecil di `spatial.css`; sidebar dan modal WebGIS kini memakai role page/section/card/body/label/caption berbasis `rem`. `ui-components.css` tidak dimuat sebagai komponen oleh `spatial.html`; ukuran caption padat di sana tetap dimigrasikan bertahap saat komponennya benar-benar disentuh, bukan melalui override global.
- [ ] **Audit browser zoom & reflow pada WebGIS.** Pemeriksaan viewport-ekuivalen 80%, 90%, 100%, 125%, 150%, 200% dan 320 CSS px selesai tanpa overflow horizontal pada panel/dialog yang diuji. Audit Edge 2026-10-21 juga menyelesaikan alur unggah, HSS, Modular Drainage Area Ratio, Machine Learning, FJ Mock, dan ekspor dari browser nyata. Uji zoom desktop asli Chrome dan Edge masih belum dapat dinyatakan lulus: koneksi audit hanya mengendalikan DOM halaman, bukan shortcut/menu zoom browser; peta tetap dipisahkan dari kontrol di sekelilingnya.
- [x] **Evaluasi fixed dimensions/cascade.** Meninjau sidebar, dialog, kontrol hydro, daftar indikator, `overflow`, dan breakpoint; memperbaiki hanya reflow 430 px serta wrapping modal yang terbukti perlu. Tidak ada konversi `px` massal.
- [ ] **Audit keyboard dan accessibility.** Trap fokus dan pengembalian fokus modal, label pemilih DTA HSS, serta reduced-motion spinner sudah diperbaiki dan diuji pada modal unggah. Verifikasi menyeluruh focus-visible, target sentuh, contrast light/dark, dan zoom desktop asli masih terbuka bersama uji browser native.

## P2 — Validasi dan maintainability

- [ ] Profilkan Modular Drainage Area Ratio di Vercel sebelum mengaktifkan kembali parameter selain Luas DTA; bandingkan cold/warm run dan waktu pemuatan data spasial.
- [ ] Jalankan subset tes Python sesuai modul yang disentuh dan dokumentasikan perintah + hasilnya; baseline suite lengkap apabila dependency/runtime fixture memungkinkan.
- [ ] Pastikan route/API + pemrosesan DTA/HSS/hidrologi tidak berubah akibat pekerjaan UI.
- [ ] Rapikan dokumen yang terbukti duplikat/usang, tetapi lakukan **archiving terlebih dahulu** (`docs/archive/`) dengan pembaruan link dan persetujuan, bukan menghapus massal.

## Completed

- [x] Menyusun 11 dokumen domain dari snapshot source DTA dan menautkannya pada README/AGENTS/SPEC. **Hanya inspeksi statis; belum menggantikan audit dokumen checkout lokal atau uji runtime.**
