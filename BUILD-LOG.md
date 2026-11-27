# NovelOS v2 Build Log — manhwa → video pivot

**Date:** 23 Nov 2026 (WIB)
**Ordered by:** Tuan — "Langsung eksekusi saja"
**Source:** Gemini v2 files (schemas.py, pipeline.py, composition.py) + SYNC-NOTES.md, verified against the real v1 code before applying.
**Environment:** `~/workspace/novelos-v2/venv` (Python 3.12.3; pydantic, sqlalchemy, fastapi, PIL, pytest, edge-tts). Run tests with `./venv/bin/python -m pytest tests/ -q`. ffmpeg/ffprobe 8.1.2 installed; filters `zoompan`, `xfade`, `subtitles` available.

## 1. Files placed (Gemini v2, as-is)

- `novelos/models/schemas.py` — v2 schemas (Script/Scene/Shot, NarrationLine, ShotDirection, Storyboard, Verdict). Verified import OK, `aspect_ratio` defaults to `16:9`.
- `novelos/pipeline.py` — v2 9-step workflow (script → storyboard → narrative QA → TTS audio → render + QC → FFmpeg assembly → human gate → export). One bug found and fixed during testing, see §4.
- `novelos/engine/composition.py` — **MERGE, not replace**: all v1 PIL code kept (`WIDTH=800`, `Composition`, `draw_dialog`, `compose`) so the PNG/PDF export path and `test_units.py` still work, plus the v2 FFmpeg video assembler (`ShotClip`, `VideoComposition`, `build_srt`, `compose_video`). The two gaps Muse found in Gemini's v2 composition are fixed here (see §3).

## 2. Contract sync (per SYNC-NOTES.md)

- `novelos/agents/writer.py` — SYSTEM prompt requests JSON with `shots`/`lines` (kinds `narration`/`dialogue`/`sfx`, `emotion_tone` for TTS), "10 to 15 shots", lines under 400 chars; `check_semantics` iterates `scene.shots`, messages say "shot N".
- `novelos/agents/director.py` — rewritten: SYSTEM prompt requests `{"directions": [...]}`; `plan(text, shots)` returns `Storyboard` with `directions` (validates length, falls back to deterministic directions); `default_layout` replaced by `default_direction(camera)` (wide/establishing → `zoom_out`, close-up → `zoom_in`, else `zoom_in`; `min_duration_sec` 3.0; `subtitle_style` `bottom_box`; `transition` `cut`).
- `novelos/models/adapters.py`
  - `MockText._script` returns v2 shape (`shots` + `lines`; kinds mapped speech/thought → `dialogue`, narration → `narration`, sfx → `sfx`; `emotion_tone` from the beat).
  - `MockText._storyboard` returns `{"directions": [...]}` (camera → motion mapping).
  - NEW `TTSAdapter` — Microsoft Edge TTS (`edge-tts`, 100% free, no API key), `synthesize(text, voice_id) -> tuple[bytes, float]`; duration via ffprobe, fallback length estimate; lazy `edge_tts` import so the module survives without the package. **NOT verified live** (needs network to Microsoft's endpoint).
  - NEW `MockTTS` — offline deterministic: real silent MP3 rendered with ffmpeg (duration = max(1.0, len(text)/13.0) s), so the assembler decodes it exactly like real TTS.
  - NEW `_ffprobe_duration()` helper and `make_tts(settings)` (`mock` → MockTTS, `edge-tts` → TTSAdapter). Existing MockText/MockImage/Gemini/OpenRouter untouched.
  - One mock-data fix found by testing: beat 9 (extreme close-up) had empty `lines: []`, but v2 `ScriptShot.lines` requires `min_length=1` — gave it one `sfx` line (`DEG`) so the beat stays a silent visual beat while satisfying the schema.
- `novelos/engine/storage.py` — added `Storage.full_path(rel_path) -> Path` (same `_safe` traversal guard as read/write).
- `novelos/engine/publishing.py` — `export()` is dual-mode: `VideoComposition` → copies `.mp4` + `.srt` into the versioned export dir, manifest gains `video_sha256` + `total_duration_sec`; v1 `Composition` → unchanged PNG/PDF path.
- `novelos/agents/artist.py` — removed the `WIDTH` import from composition (kept as a module constant anyway); `panel_size()` now returns a video frame size (1280×720 / 720×1280); prompt wording "Vertical-scroll manhwa panel" → "Video frame for a narrated story video".
- `novelos/agents/reviewer.py` — `narrative_issues` handles v2 kinds: only `dialogue` lines are checked (speaker must be in cast and present in the shot); `narration`/`sfx` are skipped; messages say "shot N". CHECKLIST wording "manhwa panel" → "video frame".
- `novelos/config.py` — added `tts_provider` (default `mock`), `tts_voice` (default `id-ID-ArdiNeural`), `est_cost_tts` (default 0.0) + env `NOVELOS_TTS_PROVIDER` / `NOVELOS_TTS_VOICE` / `NOVELOS_EST_COST_TTS`.
- `novelos/studio.py` — `build()` now passes `make_tts(s)` to `Pipeline` (new `tts` argument).
- `novelos/cli.py` — new subcommand `edit-narration`; `edit-dialog` kept as a deprecated alias.
- `novelos/api.py` — new `PUT /shots/{pid}/narration` → `edit_narration`; `PUT /panels/{pid}/dialog` kept as a deprecated alias; `GET /episodes/{eid}/panels` unchanged (table is still `panels`).
- `novelos/db.py` — no schema change (Panel table fields are generic JSON, confirmed: `spec`/`dialog`/`layout` hold shots fine). Only the status comment updated (`voiced` step added).
- `pyproject.toml` / `.env.example` — `edge-tts` as optional dep (`tts = ["edge-tts>=6"]`); env vars documented.

## 3. The two composition.py gaps — FIXED (verified by tests)

a. **`transition` was stored but never used (all joins were hard cuts).** Now implemented for real:
   - `_timeline(clips)` computes effective start times + crossfade overlaps once, shared by `build_srt` and the assembler so subtitles and video agree.
   - `crossfade` → real `xfade` (transition=fade) + `acrossfade` join, re-encoded with the same codec parameters as the segments so later concat-copy joins keep working.
   - `fade_black` → `fade=t=in/out` (video) + `afade` (audio) baked into each segment; durations unchanged (fade length `min(0.5, dur/2)`).
   - `cut` → concat demuxer stream copy, as before.
b. **`motion == "ai_video"` silently fell back to `zoom_in`.** Now explicit: `_render_segment` records a warning (`"motion 'ai_video' is not implemented yet — falling back to zoom_in"`) and `_motion_filter` documents the same. No fake video is claimed.

## 4. Bug found by testing (Gemini's v2 pipeline.py)

`edit_narration` called `_step_audio` BEFORE checking `ep.status in ("awaiting_approval", "approved", "exported")` — but `_step_audio` sets `ep.status = "voiced"` when it generates audio, so the re-assemble branch never triggered and an approved episode got stuck at `voiced` with approval still set. Fixed in `novelos/pipeline.py`: the pre-edit state is captured in `was_past_gate` before `_step_audio` runs. Test `test_narration_edit_does_not_touch_art_and_cancels_approval` failed before the fix, passes after.

## 5. Test results

Baseline v1 (before the pivot): **21 passed**.

Final v2 run (23 Nov 2026, after all fixes):
```
26 passed, 1 warning in 226.98s (0:03:46)
```
(The 1 warning is a Starlette deprecation notice about `httpx` + `TestClient`; unrelated to the build.)

- `tests/test_pipeline.py` — updated to v2 contracts: `r["shots"]` (was `r["panels"]`), preview `previews/ep001.mp4`, export checks `video`/`srt`/`manifest` + MP4 `ftyp` magic + `total_duration_sec > 0`, `test_dialog_edit_...` renamed to `test_narration_edit_...` (uses `edit_narration`, kind `narration`), `BadWriter`/`Ghost` rewritten in v2 shape (shots/lines, `directions`, kind `dialogue`).
- `tests/test_api.py` — uses new route `PUT /shots/{pid}/narration` with kind `dialogue`, 500-char text → still 422 (max_length 400).
- `tests/test_units.py` — **unchanged** (v1 PIL composition kept working).
- `tests/test_video.py` — **NEW** (5 tests): SRT timing with crossfade overlap (3s + 4s − 0.5s = 6.5s; 2nd entry starts 00:00:02,500), `compose_video` produces a playable .mp4 (ffprobe duration > 0), crossfade shortens total duration (3+3 → 5.5s), fade_black keeps duration (3+3 → 6.0s), ai_video warns + falls back.
- Full mock produce takes ~43 s per episode (12 shots × 1280×720 zoompan @ 24fps, `veryfast` preset). Do not lower the resolution to make tests faster.

## 6. Mock end-to-end produce (CLI, verified live)

```
NOVELOS_HOME=/tmp/novelos-e2e
python -m novelos init            -> {"project": "sample-manhwa", ...}
python -m novelos new --project sample-manhwa "<premise>" -> {"episode_id": 1}
python -m novelos produce 1      -> status "awaiting_approval", shots 12, passed 12, failed 0,
                                    first_attempt_pass_rate 1.0, renders 12, qc_reports 12,
                                    estimated_cost_usd 0.0, seconds_this_run 42.57
ffprobe previews/ep001.mp4       -> duration=36.041016, size=825438 bytes (playable)
python -m novelos approve 1      -> {"approved": 1}
python -m novelos export 1       -> version 1, exports/ep001/v1/episode.mp4 (825438 B) +
                                    episode.srt + manifest.json (video_sha256, total_duration_sec 36.0)
ffprobe exports/ep001/v1/episode.mp4 -> duration=36.041016
```

Warnings on the exported video (by design, not errors): shots 5, 9, 10 use a silent audio track — they are sfx-only shots (no narration/dialogue text), so `_step_audio` leaves `audio_path` empty and the assembler substitutes silence. Their duration is `min_duration_sec` (3.0 s).

Human gate intact: `export` without `approve` raises `StateError`; `edit_narration` resets approval and re-assembles. BudgetGuard intact (budget test passes with the same 4-render / $0.40 math as v1; `est_cost_tts` is 0.0 on the free tier).

## 7. Remaining gaps (honest list)

1. **`ai_video` motion is a documented fallback, not real video.** A shot with `motion="ai_video"` renders as `zoom_in` with a warning. Real AI video clips (Veo/Kling/Wan) need a new render path — not implemented.
2. **Real TTS never tested live.** `TTSAdapter` (edge-tts) is installed and imports, but no live call to Microsoft's endpoint was made (network-dependent, untested here). `MockTTS` is what all tests and the sample run use. Voice selection per character reads `character.state["voice_id"]` — no character in the sample project sets one, so the default voice is used.
3. **Real image providers never tested live.** Gemini/OpenRouter adapters are still "not live-verified" (same as v1). All renders in tests use `MockImage` (gradient + noise).
4. **Character consistency still unproven.** Same as v1: reference images are placeholders; no proof the same character looks identical across shots.
5. **Transitions are implemented, but crossfade quality is unreviewed.** The xfade join is verified by duration math + ffprobe only; nobody has watched the output video end-to-end.
6. **Performance:** a 12-shot 720p episode takes ~43 s of FFmpeg rendering per produce run on this VM (no GPU). A 15-shot 9:16 episode will be slower. This is expected, not a bug.
7. **The exported MP4's subtitles are burned in** (`burn_subtitles=True` default) and the `.srt` is also exported; word-level highlight (`word_highlight` style) is accepted by the schema but rendered exactly like `bottom_box` (no per-word timing exists yet).

## 8. Zeno/Achilles run — first real episode (23 Nov ~20:56 WIB, proactive)

Tuan asked at 20:09 to try a Zeno/Achilles-paradox script. The first validation
failed only because v1 schemas were still in place (expected `panels`). After
the v2 build, the script was written fresh and run end-to-end.

- **Script:** `zeno-script.json` — "Zeno dan Achilles — Paradoks yang Tak
  Pernah Selesai", 3 scenes, 6 shots, Indonesian narration. Validates clean
  against v2 schemas (`Script.model_validate` OK).
- **Driver:** `run-zeno.py` — creates episode 1 in project `sample-manhwa`,
  injects the validated Script + Panel rows + per-shot layouts (motions
  zoom_in/pan_left/zoom_out/pan_right; transitions crossfade x4 + fade_black
  on shot 5 + cut on shot 6), then produce -> approve -> export.
- **Result:** produce `awaiting_approval`, 6 shots, 6 passed, 0 failed,
  first-attempt 1.0, cost $0.00, 49.56 s. Export v1: `episode.mp4` 1,324,711 B,
  45.95 s, h264 1280x720 + aac, no warnings. SRT timings respect the
  crossfade overlaps (e.g. shot 2 starts 0.5 s before shot 1 ends). Frames
  checked: subtitles burned in correctly, crossfade visible.
- **Narration audio:** NOT edge-tts. The pipeline's live TTS path was tested
  and is blocked in this VM (see below), so narration was made with Muse TTS
  (`/opt/hatch/bin/tts`, language id, voice Helio) — 6 clips, 5.28–12.41 s
  each, ~48 s total — and injected via the pipeline's own skip logic
  (`_step_audio` skips panels that already carry audio_path + duration_sec).
- **Visuals:** MockImage gradients ("MOCK PANEL refs=0" label visible) — real
  image providers still not live (same gap as v1). The video is a real
  pipeline product with a real voice; only the imagery is placeholder.

### edge-tts live test — why it fails in this VM (diagnosed 23 Nov 20:53)

1. Direct connection fails: local DNS returns a fake IP (198.18.4.253) for
   speech.platform.bing.com, so the TLS handshake gets WRONG_VERSION_NUMBER.
   Real IPs via Google DoH: 150.171.28.10 / 150.171.27.10.
2. With the egress proxy passed explicitly to `Communicate(proxy=...)`, the
   connection reaches Microsoft but TLS verification fails: edge-tts pins
   its SSL context to certifi's Mozilla bundle, which lacks the VM's egress
   CA (`hatch-egress-ca.crt`, in the system bundle
   `/run/hatch/egress-tls/ca-bundle.pem`). curl works because it uses the
   system bundle. /etc/hosts is read-only, so no DNS override is possible.
3. With proxy + system-CA context, TLS succeeds but Microsoft returns **403**
   on the WebSocket handshake (SkewAdjustmentError: no Date header). VM clock
   is correct (4 s off Google), so this is not clock skew — likely the
   egress IP / proxy is rejected by Microsoft's edge. No code fix in the
   adapter would change this; it is environmental.
4. Consequence: `TTSAdapter` (edge-tts) remains "not verified live" — it
   needs a network path to Microsoft that this VM does not have. On a normal
   network (Tuan's laptop, a VPS without this proxy) it should work
   unmodified. A future fix could pass the proxy + system CA bundle, but it
   would not clear the 403 here.

## 9. Zeno/Achilles run — REAL images (23 Nov ~22:42 WIB, on Tuan's order)

Tuan generated 6 frames with Gemini (from the per-frame prompts in
`~/workspace/your_files/zeno-achilles-prompt-per-frame.txt`) and asked Muse
to put them into the video. This run replaces the MockImage gradients with
those real frames; narration and script are unchanged from §8.

- **Frames:** `~/workspace/your_files/zeno-frames/frame-01.jpg` .. `frame-06.jpg`
  (JPEG 1376x768, 16:9, ~122–181 KB each). Mapping, file order = shot order:
  01 garis start Achilles + kura-kura; 02 kura-kura di depan, Achilles
  mengejar; 03 Achilles sprint mencapai titik awal kura-kura; 04 lintasan
  panjang, kura-kura foreground; 05 garis emas tak berujung; 06 garis finis,
  penonton bersorak. Note: frames 02 and 03 are both sprint scenes — the
  mapping above is the parent agent's read of the image contents; the driver
  uses file order as-is and never re-guesses.
- **Adapter:** NEW `novelos/models/file_image.py` — `FileImage` (name
  `file-image`), `generate(prompt, references, size)` returns
  `normalize_image(frame_bytes, size)` (cover + centre crop to 1280x720 PNG).
  Mapping is by shot description (the prompt embeds
  `Scene: {description}`, unique per shot), NOT by call order, so a pipeline
  retry for a panel can never serve the wrong frame; an unmatched prompt
  raises ProviderError instead of failing silently. `review()` returns None,
  like MockImage. No frozen code touched (schemas/pipeline/composition
  unchanged).
- **Driver:** NEW `run-zeno-real.py` (run-zeno.py untouched). Builds the
  Pipeline exactly like `studio.build()` but injects FileImage in place of
  `make_image(s)`; same DIRECTIONS (crossfade x4, fade_black shot 5, cut
  shot 6), same produce -> approve -> export flow.
- **Narration:** the /tmp/zeno-narration clips from §8 were wiped by a VM
  reset, so narration was RE-SYNTHESIZED with Muse TTS
  (`/opt/hatch/bin/tts`, language id, voice Helio — resolves to
  avocado_v2:MAI_03) into a permanent dir `zeno-narration-real/` (not /tmp):
  s01 7.97 s, s02 5.47 s, s03 8.04 s, s04 5.83 s, s05 7.44 s, s06 10.51 s
  (~45.26 s total). edge-tts was NOT retried — the §8 diagnosis still stands
  (environmental 403), so real-voice narration here is Muse TTS again, not
  edge-tts. No MockTTS fallback was needed.
- **Run incident (fixed, driver only):** first run of run-zeno-real.py
  crashed with `NameError: session_scope` (missing import) AFTER creating an
  empty episode 2 but BEFORE injecting panels. Fixed the import, re-ran; the
  second run created episode 3 and completed. Episode 2 stays in the DB as
  an empty row (no panels) — harmless, left as-is.
- **Result:** produce `awaiting_approval`, episode 3, 6 shots, 6 passed,
  0 failed, first-attempt 1.0, cost $0.00, 87.65 s. FileImage calls logged
  in order, exactly 6, no retries: shot 1 -> frame-01 ... shot 6 ->
  frame-06. Export v1: `episode.mp4` 4,535,604 B, 43.26 s, no warnings.
  Copied to permanent location:
  `~/workspace/your_files/zeno-achilles-ep001-real.mp4`
  (sha256 e2b0b0b4a81928173ba83034384c9600b938a36f737aa6ae3e3335afc6e094cf).
- **Verification (ffprobe + visual frame check):** h264 1280x720 @ 24 fps +
  aac, duration 43.46 s, playable. Frames extracted at t=2 s (shot 1) and
  t=40 s (shot 6) and inspected: real Gemini imagery (Achilles at the start
  line; Achilles crossing the finish rope, crowd cheering), subtitles burned
  in with the correct narration per shot, no "MOCK PANEL" label anywhere.
  SRT timings respect crossfade overlaps (shot 2 starts 0.5 s before shot 1
  ends). Manifest `total_duration_sec` 43.26, `video_sha256` present.
- **Remaining gaps (unchanged from §7, plus one new):** ai_video still
  fallback-only; edge-tts still not verified live; character consistency
  across frames is Gemini's, not the pipeline's (Achilles' face/kit visibly
  changes between frames — e.g. helmeted in frame-03 vs bare-headed in
  frame-01); crossfade quality still only verified by duration math +
  frame stills, not a full watch-through; the video is 16:9 (43 s) while
  the Shorts/TikTok format is 9:16 — a vertical cut is a separate step.

## 10. v1 manhwa episode run — vertical PNG + PDF (23 Nov ~22:52 WIB, on Tuan's order)

Tuan asked to run NovelOS v1 (the original manhwa path) to compare against
Google Flow. The pipeline underneath is now v2, so this is an honest hybrid,
not pure v1 — see the gaps below.

**What ran:** new driver `run-v1-episode.py` (run-zeno.py pattern). It calls the
real MockText writer for the sample project ("Regresi Sang Pedang", premise:
Kael wakes 3 years before the destruction), injects the script with
`aspect_ratio="9:16"` (a legitimate Script field, default 16:9) so renders
come out portrait 720x1280, creates the 12 panels, then runs the real
pipeline produce (storyboard, QA, MockTTS audio, render, assemble) -> approve.
The v1 export itself uses the untouched v1 code: PIL `compose()` (vertical
stack + dialog bubbles) and `publishing.export()` (episode.png + episode.pdf
+ manifest). No frozen file was modified.

**Result:** episode 4, 12 panels, 12 passed, 0 failed, first-attempt 1.0,
cost $0.00, 25.35 dtk. Composed 800x17208 px, 12 panels, warnings=[].
- `~/workspace/your_files/novelos-v1-episode.png` — 491.084 byte, 800x17208 RGB.
- `~/workspace/your_files/novelos-v1-episode.pdf` — 519.417 byte, 12 pages
  (pdfinfo: 576 x 1023.84 pts/page, PDF 1.4, not encrypted).
- Storage originals: `data/storage/exports/ep004/v1/` (episode.png/.pdf/manifest.json).
- Verified visually: panel 5 (SFX "ZZZRRT" in big yellow letters over the mock
  gradient), panels 1-2 (narration box "Semuanya dimulai di sini." + speech
  bubble "Ini tidak seharusnya terjadi."), and PDF page 1 rendered via pdftoppm
  (same panel 1). No panel is cut in half in the PDF (build_pdf packs whole panels).

**Honest gaps (what is NOT v1 murni):**
1. The pipeline is v2: Shot schemas, video assembly also runs as a by-product
   (previews/ep004.mp4 exists but was not delivered); the v1 part is only the
   compose + export step.
2. Dialog kinds: v2 collapsed v1 speech+thought into "dialogue", so the driver
   maps every "dialogue" line to a v1 "speech" bubble — there are no thought
   clouds in this episode (the original v1 mock had them).
3. Art is MockImage gradients with character placeholders (KAEL_001/VORN_001)
   and a "MOCK PANEL refs=N" label — same as v1 mock, not real art.
4. Panels are 800x1422 (9:16) — this matches the v1 design (publishing.py notes
   the tallest allowed panel is 1.8 x 800 = 1440), but the v1 original's exact
   render size was never recorded; 9:16 was chosen because the bible style says
   "vertical webtoon framing".
5. MockTTS audio was generated (silent) by the pipeline but is unused by the
   v1 PNG/PDF export.

---

## 2026-11-27 — Refactor "rooms" langkah 1-2 (disetujui Tuan 27 Nov 2026)

Struktur baru: `core/` (pintu) + `libs/` (alat) + `rooms/manhwa/` (ruangan pertama).
Backup lengkap tree sebelum refactor: `~/workspace/novelos-v2-backup-2026-11-27/`
(dicek: diff kosong, 2374 file identik, kecuali `__pycache__`).

**Langkah 1 — pindah tanpa ubah perilaku (26/26 hijau, 237.47s):**
- `models/` -> `libs/models/` (adapters, file_image, schemas)
- `engine/budget.py` -> `core/budget.py`, `engine/storage.py` -> `core/storage.py`
- `agents/` -> `rooms/manhwa/agents/` (writer, director, artist, illustrator, reviewer)
- `engine/composition.py` di-split: v1 (Composition/compose/draw_dialog) ->
  `rooms/manhwa/composition.py`; v2 (ShotClip/compose_video/build_srt, FFmpeg) ->
  `libs/media/video.py`
- `engine/publishing.py` -> `rooms/manhwa/publishing.py`,
  `engine/characters.py` -> `rooms/manhwa/characters.py`,
  `engine/quality.py` -> `rooms/manhwa/quality.py`; `engine/` dihapus
- Tes: `test_pipeline/video/api.py` -> `tests/rooms/manhwa/`; `test_units.py`
  di-split: budget+storage -> `tests/core/test_budget_storage.py` (2),
  sisanya -> `tests/rooms/manhwa/test_units.py` (8). `projects/` sudah ada, tak diubah.

**Langkah 2 — contract + runner, manhwa sebagai ruangan pertama (33/33 hijau, 226.27s):**
- Baru: `core/contract.py` (StepSpec + ProjectRoom), `core/runner.py` (Runner),
  `core/registry.py` (lazy load by key, `manhwa` terdaftar),
  `core/approval.py` (check_approvable/check_exportable/mark_approved),
  `core/manifest.py` (build_manifest, pure function),
  `rooms/manhwa/room.py` (ManhwaRoom, key `manhwa`),
  `tests/core/test_import_rules.py`, `tests/core/test_runner.py` (6 tes).
- `BudgetGuard.check()` baru (pre-check non-mutating); `charge()` memakainya, pesan error sama.
- `Pipeline` pindah ke `rooms/manhwa/pipeline.py`; `produce()` jalan lewat
  Runner + registry; `approve()`/`export()` lewat `core.approval`/`core.manifest`.
  `novelos/pipeline.py` tinggal shim re-export (CLI/API/studio/tes tak berubah).
- Estimasi langkah = satu unit kerja, 0 bila langkah sudah selesai — jadi resume
  dan jeda anggaran berperilaku persis seperti sebelumnya (tes budget
  `passed == 4` lalu resume tetap lolos).
- Smoke CLI langsung (NOVELOS_HOME=/tmp/novelos-smoke, mock): init -> new ->
  produce `awaiting_approval` 12/12 -> approve -> export v1 (mp4 828.109 byte,
  36.0s) -> status `exported`. API: `test_full_flow_over_http` (termasuk 409
  sebelum approve) lolos di suite.

**Tidak dikerjakan (langkah berikut):** langkah 3 (`project_type` di tabel
Project), langkah 4 (`rooms/explainer`). "Satu Soal, Tiga Cara" tidak disentuh.
Tidak ada dependensi baru, tidak ada push GitHub.

---

## 2026-11-27 — Refactor "rooms" langkah 3-4 (subagent, selesai)

**Koreksi soal contoh (verifikasi materi 25 Nov, BUKAN asumsi tugas):** tugas
menyebut cara ke-3 "grafik", tapi materi Tuan yang terverifikasi — 6 keyframe
`~/workspace/satu-soal-tiga-cara/`, naskah + narasi
`~/workspace/satu-soal-tiga-cara/build-narration.sh`, dan memori 25 Nov —
menyatakan metode episode 1 adalah **substitusi, eliminasi, MATRIKS** (adegan
5 = matriks, narasi: "Cara tiga, matriks"). Soal: bagi 5 permen, Doni 3,
Dina 2 → sistem x + y = 5, x − y = 1, solusi x = 3, y = 2. Narasi 6 adegan
dipakai verbatim dari naskah 25 Nov. Room memakai matriks; ganti ke grafik
hanya atas perintah Tuan.

**Langkah 3 — `project_type` di tabel Project:**
- `novelos/db.py`: kolom `Project.project_type` (String(40), default
  "manhwa") + `ensure_project_type_column(engine)` — ALTER TABLE idempotent
  yang dipanggil `init_db` setelah `create_all` (create_all saja tidak
  menambah kolom di DB lama). Terverifikasi di DB produksi
  `data/novelos.db`: kolom bertambah, `sample-manhwa` terbaca "manhwa",
  4 episode utuh, tidak ada baris berubah selain backfill default.
- `novelos/sample.py`: `load_project(..., project_type=...)` (dari JSON atau
  override CLI; mismatch dengan proyek yang sudah ada → ValueError) +
  `ensure_project(factory, slug, project_type, ...)` (buat proyek kosong).
- `novelos/core/registry.py`: `"explainer"` terdaftar di `_LOADERS`.
- `novelos/rooms/manhwa/pipeline.py`: `produce()`/`export()` merutekan
  berdasarkan `project_type` episode (bukan lagi hardcode "manhwa");
  `produce` kini juga menangkap ValueError → `needs_attention` (dipakai
  room explainer untuk verifikasi matematika yang gagal);
  `edit_narration` menolak episode non-manhwa dengan StateError.
- `novelos/core/errors.py` (BARU): `StateError` pindah dari pipeline manhwa
  ke core — explainer butuh error yang sama (CLI/API menangkapnya by
  identity) dan room tidak boleh mengimpor room lain (aturan impor juga
  menghitung impor `TYPE_CHECKING`, jadi room explainer tidak mengimpor
  `Pipeline` manhwa bahkan untuk anotasi tipe). Identitas diverifikasi:
  `novelos.pipeline.StateError is novelos.core.errors.StateError`.
- CLI: `init --type {manhwa,explainer}`, `new --type ...` (buat proyek bila
  belum ada; mismatch → error, exit 1), `projects` (daftar + tipe).
  API: `POST /projects`, `GET /projects`, `POST /episodes` terima
  `project_type` opsional (hanya bila proyek belum ada).
- `projects/sample-explainer/project.json` (BARU): proyek contoh explainer
  ("Satu Soal, Tiga Cara", genre education).
- Tes: `tests/core/test_project_type.py` (5 tes: default manhwa, migrasi DB
  lama + idempotent, unknown type ditolak, room explainer terdaftar +
  bentuk steps, mismatch type ditolak).

**Langkah 4 — `rooms/explainer/` (ruangan kedua):**
- `bible.py`: gaya stickman (Doni oranye bertopi, Dina biru berkuncir dua,
  permen pink, kertas off-white), soal SPLDV + solusi + 6 adegan + narasi
  verbatim 25 Nov.
- `schema.py`: pydantic `LinEq/Relation/RowOp/MathStep/Method/LinearSystem/
  ExplainerScene/ExplainerScript` — validasi bentuk + urutan metode
  (substitusi, eliminasi, matriks) dan adegan (hook, soal, substitusi,
  eliminasi, matriks, kesimpulan). Matematika TIDAK dicek di sini.
- `math_verify.py`: verifikasi NYATA (Fractions eksak, aturan Cramer):
  menyelesaikan sistem sendiri, lalu menurunkan ulang tiap langkah tiap
  metode dari persamaan sistem (given/rearrange proporsional, substitusi
  simbolik, add/subtract, scale, read-off, row_op matriks) + tiap persamaan
  harus dipenuhi solusi + hasil tiap metode harus sama dengan solusi.
  Menolak: jawaban akhir salah, langkah substitusi/eliminasi salah,
  read-off salah, row_op salah, matriks bukan sistem, relasi palsu, sistem
  singular (determinan 0).
- `writer.py`: `default_script()` = naskah episode 1 terverifikasi (dicek
  sendiri saat dibangun — gagal berarti AssertionError); `write_script()`
  memakai adapter teks bila mendukung task `explainer_script`, dan naskah
  provider lain tetap divalidasi skema + diverifikasi matematikanya
  (gagal → ValueError → episode `needs_attention`, tidak ada video salah
  yang terbit). MockText → naskah default deterministik.
- `stickman_draw.py`: PIL saja (matplotlib TIDAK terinstal — tidak ada
  dependensi baru sama sekali). Frame 720×1280: judul, papan tulis berisi
  rumus, Doni/Dina, tumpukan permen sesuai jumlah (soal: 3 vs 2 —
  diverifikasi dengan menghitung piksel pink per sisi). Deterministik.
- `assemble.py`: `clips_for_episode` + `assemble_preview` (compose_video
  libs/media, 9:16, motion static agar rumus tetap terbaca) + export
  berversi lokal (duplikasi bentuk export manhwa yang disengaja — room
  tidak boleh mengimpor room lain).
- `room.py`: `ExplainerRoom` (key "explainer") — steps `script → verify →
  audio → draw → assemble` (human_gate di assemble), memakai core
  (contract/runner/registry/budget/approval/manifest) + libs (media/ffmpeg,
  MockTTS). Verifikasi diulang di step `verify`; gagal → run berhenti →
  `needs_attention` sebelum frame digambar. State di tabel Episode/Panel
  yang sama (1 Panel per adegan: spec = adegan, dialog = narasi, layout =
  metadata audio). `export()` memakai approval + manifest core.
- Tes: `tests/rooms/explainer/` — schema (7), math_verify (9, termasuk
  semua penolakan di atas), writer (4, termasuk provider dengan sistem
  SPLDV kedua yang benar (3x+y=10, x−y=2 → 3,1) diterima + yang salah
  ditolak), stickman (3), assemble (2), room (6: e2e produce→approve→
  export, export ditolak sebelum approve + berversi, matematika salah
  berhenti sebelum frame, manhwa + explainer berdampingan, CLI, API).

**Smoke CLI (NOVELOS_HOME=/tmp/novelos-explainer-smoke, mock):**
init → new → produce `awaiting_approval` 6/6, 58.9 dtk → approve → export v1.
`episode.mp4` 788.104 byte, 720×1280 h264+aac, 76,18 dtk (ffprobe) +
`episode.srt` + `manifest.json`. Disalin ke
`~/workspace/your_files/explainer-satu-soal-tiga-cara-ep001.mp4`
(sha256 50be04067de17be0886ac5010c3ad02de2532fc40e85200feb44dd3275d60bcd)
dan frame soal ke `explainer-satu-soal-tiga-cara-frame-soal.png`.

**Jujur — yang TIDAK terverifikasi / batasan:**
1. Durasi smoke 76 dtk, bukan 63,3 dtk narasi asli: MockTTS mengestimasi
   durasi dari panjang teks (~13 karakter/detik), jadi totalnya lebih
   panjang dari narasi rekaman 25 Nov. Audio mock adalah sunyi (silent
   MP3), bukan suara. Dengan TTS asli durasi ≈ 63 dtk. edge-tts tetap
   belum terverifikasi live di VM ini (diagnosis 23 Nov masih berlaku).
2. Frame stickman digambar kode (PIL), BUKAN keyframe AI 25 Nov — gaya
   disamakan (warna/karakter/permen), tapi bukan gambar yang sama. Keyframe
   asli tidak dipakai sebagai aset room (belum ada jalur impor aset).
3. Kualitas visual video hanya dicek via frame stills (2 frame dilihat)
   + ffprobe — tidak ada tontonan penuh dari awal sampai akhir.
4. `produce` kini menangkap ValueError → needs_attention: perilaku baru
   untuk error ValueError di langkah manhwa juga (sebelumnya ValueError
   lolos ke CLI sebagai error exit 1; kini episode jadi needs_attention).
   Tes manhwa tetap hijau; dicatat sebagai perubahan perilaku yang
   disengaja.
5. Tidak ada dependensi baru, tidak ada push GitHub, tidak ada perubahan
   perilaku room manhwa (tes manhwa hijau).
