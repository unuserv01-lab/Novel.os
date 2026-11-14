# Novel.os

Pipeline produksi episode manhwa vertikal: **premis → naskah → storyboard → render panel + QC → komposisi → persetujuan manusia → ekspor PNG panjang + PDF.**
Ini irisan vertikal **MVP 0.1** dari `NovelOS — Backlog V1` (Fase 0–5, versi ringkas). Rp0 secara default.

## Status jujur

| Bagian | Status |
|---|---|
| Pipeline end-to-end dengan adapter **mock** | **Teruji** — 21 tes lolos; pengaman utama diuji dengan mutasi (merusaknya membuat tes gagal) |
| Adapter **Gemini teks** (`gemini-3.8-flash`) | **Teruji live 2026-11-14** — `selftest-live` lolos (JSON mode). Kadang 503 "high demand", retry saja |
| Adapter **Gemini gambar** (`gemini-3.1-flash-image`) | **Tidak bisa di free tier** — limit harian 0 (429), butuh billing. Jangan andalkan tanpa kartu |
| Adapter **Pollinations gambar** (`flux`, gratis, tanpa key) | **Teruji live 2026-11-14** — satu panel 800x1280 kembali ~7 detik, kualitas layak draf. Watermark tetap muncul meski `nologo=true`; referensi gambar tidak dikirim (hanya deskripsi teks) |
| Adapter **OpenRouter teks** | **Teruji live 2026-11-14** — model gratis `nvidia/nemotron-3.5-super-vl:free`. Model default di `.env.example` (google/gemini-2.5-flash) berbayar, jangan pakai dengan key $0 |
| Adapter **OpenRouter gambar** | **Belum teruji live.** Tidak ada model gambar gratis di OpenRouter saat ini (semua model `:free` hanya output teks) |
| QC visual oleh model | Ada jalurnya (`image.review`), **belum pernah dijalankan** pada gambar asli. Dengan mock, hanya pemeriksaan otomatis (ukuran, kosong, duplikat) yang jalan |
| Konsistensi karakter | **Belum terbukti.** Mekanismenya ada (referensi + blok prompt + QC), tapi risiko terbesar proyek ini baru bisa dinilai dengan gambar asli |
| Referensi karakter sample | **Placeholder** (kotak warna). Ganti dengan gambar asli lewat `add_reference` |
| "Siap produksi" | **Belum.** Ini fondasi yang disiplin, bukan produk jadi |

## Sengaja berbeda dari backlog
- SQLite default (PostgreSQL lewat `DATABASE_URL`, paket `psycopg`); belum dites di PostgreSQL.
- Tanpa Next.js Studio: antarmuka = CLI + FastAPI. Tanpa Redis/RQ: render berjalan berurutan (resumable).
- Tanpa tabel `scenes` terpisah (nomor adegan ada di panel). Tanpa Docker, OpenCV, FFmpeg, LoRA.
- PDF memuat panel utuh per halaman (800×1600), bukan potongan acak.

## Pakai
```bash
pip install -e ".[dev]"
python -m novelos init                       # DB + proyek sample (Kael, Vorn, Lyra)
python -m novelos new "premis episode"       # -> episode_id
python -m novelos produce 1                  # berhenti di awaiting_approval
python -m novelos approve 1                  # human gate
python -m novelos export 1                   # data/storage/exports/ep001/v1/{episode.png,episode.pdf,manifest.json}
python -m novelos edit-dialog <panel_id> '[{"speaker":"Kael","text":"...","kind":"speech"}]'   # tanpa render ulang; membatalkan approval
pytest
uvicorn novelos.api:app --host 127.0.0.1   # set NOVELOS_API_TOKEN; jangan buka ke internet
```
Provider nyata: salin `.env.example`, set `NOVELOS_TEXT_PROVIDER` / `NOVELOS_IMAGE_PROVIDER` dan kunci di shell, lalu `python -m novelos selftest-live`.

## Pengaman yang ada (dan diuji)
- Ekspor **ditolak** tanpa persetujuan manusia; menyunting dialog membatalkan persetujuan.
- Regenerasi dibatasi (`NOVELOS_MAX_REGEN`); versi lama aset tidak pernah dihapus.
- Budget guard memesan biaya **sebelum** memanggil API; berhenti di `paused_budget` dan bisa dilanjutkan tanpa membayar ulang panel yang sudah lolos.
- Naskah dengan tokoh/lokasi/pembicara tak dikenal gagal **sebelum** ada gambar yang dibayar.
- Dialog/bubble/SFX digambar saat komposisi, tidak pernah dibakar ke gambar panel.
- Kunci API hanya dari environment; pesan error menyensor kunci.

## Langkah berikut yang disarankan
1. `selftest-live` dengan satu kunci Gemini (free tier), lalu satu episode asli.
2. Ganti referensi placeholder dengan gambar karakter asli dan nilai sendiri konsistensinya.
3. Hanya jika itu lolos: Studio UI, antrean, PostgreSQL, Docker.
