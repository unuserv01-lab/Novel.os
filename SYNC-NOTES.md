# NovelOS v2 — Sinkronisasi Kontrak (catatan Gemini, 23 Nov 2026)

Tiga file v2 (schemas.py, pipeline.py, composition.py) memanggil modul lain
yang belum disesuaikan. Tanpa penyesuaian ini akan terjadi AttributeError.

## 1. novelos/agents/writer.py & novelos/agents/director.py

**writer.py (v1 saat ini):**
- SYSTEM prompt meminta JSON dengan key `panels` dan `dialog`.
- `check_semantics` mengiterasi `scene.panels`.
- Perlu diubah: prompt sistem memakai key `shots` dan `lines`
  (menggantikan `panels` dan `dialog`), sesuai schemas.py v2.
- `check_semantics` harus mengiterasi `scene.shots`.

**director.py (v1 saat ini):**
- SYSTEM prompt meminta JSON `{"layouts": [...]}`.
- `plan()` mengembalikan Storyboard berisi `layouts` (Layout: height_ratio, gap).
- `default_layout(camera)` mengembalikan Layout.
- Perlu diubah: output schema mengembalikan Storyboard berisi `directions`
  (ShotDirection: motion, transition, min_duration_sec, subtitle_style).
- `plan()` harus memakai `sb.directions` dan fallback membuat ShotDirection.

## 2. novelos/models/adapters.py

**v1 saat ini:** hanya ada MockText, MockImage, GeminiText, GeminiImage,
OpenRouterText, OpenRouterImage. TIDAK ada adapter TTS.

**Perlu ditambah:** class `TTSAdapter` (misal memakai edge-tts, 100% gratis
+ mutagen/ffprobe untuk membaca panjang detik .mp3 secara akurat) dengan
method:
- `synthesize(text: str, voice_id: str | None) -> tuple[bytes, float]`
  (mengembalikan audio bytes + durasi detik).
- Dipakai pipeline v2 `_step_audio`: `self.tts.synthesize(full_text, voice_id=voice_id)`.

## 3. novelos/engine/storage.py & novelos/engine/publishing.py

**storage.py (v1 saat ini):**
- Storage hanya punya `write`, `read`, `exists`. TIDAK ada `full_path`.
- pipeline v2 memanggil `self.storage.full_path(...)` di `_compose`
  (untuk asset.path, audio_rel, out_rel) — karena FFmpeg butuh path file
  lokal di disk, bukan bytes di memori.
- Perlu ditambah: `full_path(rel_path: str) -> Path` (mengembalikan path
  absolut yang sudah melewati pengecekan `_safe`).

**publishing.py (v1 saat ini):**
- `export(storage, ep_number, comp: Composition, manifest)` — menerima
  Composition (gambar PIL), menulis episode.png + episode.pdf (via build_pdf).
- pipeline v2 memanggil `publishing.export(...)` dengan `comp` berupa
  VideoComposition (video_path, srt_path, total_duration_sec).
- Perlu diubah: export harus menyalin file .mp4 + .srt dari comp.video_path
  (bukan membangun PNG/PDF), dan manifest memakai total_duration_sec.

## Status verifikasi (Muse, 23 Nov 2026)
Ketiga penyesuaian di atas sudah diverifikasi terhadap kode v1 asli
(dari Novel.os.zip) — semuanya benar-benar diperlukan, bukan asumsi.
File v2 yang sudah disimpan di ~/workspace/novelos-v2/:
- schemas.py (v2, dari Gemini)
- pipeline.py (v2, dari Gemini)
- composition.py (v2, dari Gemini) — BELUM disimpan, masih di chat
