# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`ursotts`: a CLI and a Gradio web UI that render plain-text narration scripts (English + Korean, mixed per sentence) into voice-cloned WAV/MP3/SRT using Chatterbox (Resemble AI) running locally. Built for the @ursomics video series.

## Commands

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"                # chatterbox + gradio; `pip install -e .` for dummy-engine-only work

ursotts check                          # torch device, chatterbox, ffmpeg, voice samples
ursotts preview scripts/02_intro_ko.txt  # show chunks / detected language / pauses, no rendering
ursotts batch scripts output           # render every .txt/.md in scripts/ -> output/
ursotts batch examples output/pron_test  # pronunciation test scripts
ursotts batch scripts output --engine dummy   # fast end-to-end run, no GPU or model download
ursotts say "text" -o out.wav --lang ko
ursotts ui                             # web UI at http://127.0.0.1:7860 (add --engine dummy to test)
python -m ursotts ...                  # same as the `ursotts` entry point
```

There is no test suite or linter configured. To verify changes, use `preview` (parsing/chunking), `batch ... --engine dummy` (pipeline, pauses, SRT timing, cache) and `ui --engine dummy`. `--engine dummy` also bypasses the voice-sample existence check.

## Architecture

Flow: `cli.py` → `config.load_config` → `text.parse_script` → `pipeline.Synthesizer.render` → `audio` exports. `ui.py` drives the same pipeline.

- **Parsing (`text.py`)** turns a script into a flat list of `Speech` / `Pause` items. Order: strip `#` comments and `@directive` lines → split paragraphs on blank lines → split on `[pause N]` tags → split sentences → split over-long sentences (`max_chars`) → detect language per sentence (Hangul ≥ 25% of letters ⇒ `ko`) → group consecutive same-language sentences up to `max_chars` into one `Speech` chunk.
- **Pronunciation** is applied to `Speech.text` (what the model speaks) only; `Speech.sentences` keeps the original spelling for subtitles. Steps: dictionary replacements (`apply_pronunciations`, longest match first; a value is a string or `{say, like}`; `render_say` turns dot notation `NAN.og` into one lowercase word `nanog`, and leaves text without dots unchanged), then `spell_acronyms` for all-caps 2–6 letter words (English `DNA` → `D.N.A.`; Korean Hangul letter names `DNA` → `디엔에이`). Term boundaries are Latin letters/digits only (`EDGE_L`/`EDGE_R`), so Korean particles attached to a term (`DNA를`) still match.
- **Caching (`pipeline.Synthesizer.chunk_audio`)**: each chunk's audio is stored in `cache_dir` keyed by engine name + `engine.settings()` + spoken text + lang + hash of the voice sample. Anything that changes the audio must be included in `settings()`. Cached chunks are already silence-trimmed.
- **Batch skipping (`plan_batch`/`run_batch`)**: a script is skipped only when its text and `settings_fingerprint(cfg)` (audio-affecting config keys, pronunciation table, voice-file hashes) match `output/.ursotts_state.json`. Add new audio-affecting config keys to that fingerprint. Per-file failures go to `batch_report.json` without stopping the batch.
- **Subtitles**: one SRT cue per original sentence; timing within a chunk is apportioned by character share (no forced alignment).
- **Engines (`engine.py`)**: subclass `BaseEngine` (`name`, `sample_rate`, `synth`, `settings`, `update`) and register it in `make_engine` and the `--engine` choices in `cli.py`. `torch`/`chatterbox` are imported lazily. On `mps`, `torch.load` is patched to remap CUDA-saved weights. A fixed `seed` is re-applied before every chunk. The voice sample is analyzed once with `prepare_conditionals` and reused (`_cond_key` = sample path + mtime + exaggeration); don't pass `audio_prompt_path` per chunk, which re-analyzes the voice every time. Timing per chunk is printed to the terminal.
- **Voice selection**: `voices` maps lang → sample file; falls back to `default_lang`'s sample, then any sample. `Synthesizer.voice_override` (web UI) uses one sample for all languages. `missing_voices` blocks rendering when a listed sample is missing.
- **Web UI (`ui.py`)**: tabs Speak, Pronunciation, Batch. The model loads lazily on first use and is shared. The Pronunciation tab speaks each candidate exactly as typed (via `render_say`) and saves with `upsert_pronunciation`, which edits one line and keeps the file's comments. Gradio 6 takes `theme`/`css` in `launch()`, older versions in `Blocks()`.
- **Config (`config.py`)**: YAML merged over `DEFAULTS`; `voices`, `cache_dir` and `pronunciations` paths resolve relative to the config file's directory. If the `-c` path doesn't exist, the CLI uses defaults relative to cwd.
- **Output (`audio.py`)**: WAV is peak-normalized; MP3 via `ffmpeg` with `loudnorm` to -14 LUFS, skipped if `ffmpeg` is missing.

## Pronunciation entries (pronunciations.yaml)

- Letters: each capital followed by a dot (`CD8: C.D. eight`, `TCRs: T.C.R.s`, `RNA-seq: R.N.A. seek`); `render_say` keeps such letter tokens verbatim. Never separate letters with spaces or hyphens: Chatterbox pauses at each break.
- Gene names: if the 2nd letter is a vowel (NANOG, GATA, SOX, KIR), write the word form first (`NAN.og`); spell letters (`N.A.N.O.G.`) only if the word form sounds wrong.
- Word-like sounds: syllables of 2+ letters joined by dots, stressed syllable in CAPS (`NANOG: NAN.og`); `render_say` joins and lowercases them. Put the user's description in `like:` (`NANOG: {say: NAN.og, like: "NAN as in man, og as in dog"}`).
- Korean entries: Hangul readings only (`GATA6: 가타식스`), never Latin letters.
- "Ursomics" stays as written. Mark entries checked by ear as tested; edit in place and keep comments.

## Brand

- Display name **ursoTTS** (in prose, titles, images); package, command and repo name `ursotts`.
- Brand kit in `docs/brand/` (banners, social preview, avatar, logos, favicons, palette). The README banner uses `<picture>` with light/dark versions; image paths are relative (`docs/brand/...` from README, `brand/...` from docs/MANUAL.md).
- Palette: Coral #D97757, Ink #1B1B1B, White #FFFFFF, Cream #F6EFE6, Deep Coral #C4623F, Soft Coral #F0C9B8. Typeface Poppins.
- Brand artwork is © Ursus (@ursomics) and not under the MIT license; don't alter or re-generate it.

## Project rules

- **Environment:** macOS on Apple Silicon (device `mps`). Use Python 3.13 in the project-local `.venv/`; run commands from that venv, not the system Python.
- **Public repo:** published on GitHub under MIT. Keep the code clean and readable, and keep README.md and docs/MANUAL.md beginner-friendly: plain language, copy-pasteable commands, no assumed ML background. Keep both in sync when commands or options change.
- **Two languages:** README.md / README.ko.md and docs/MANUAL.md / docs/MANUAL.ko.md. When you change one, update the other in the same commit. Korean uses polite 합니다체; commands, file names and code stay in English. Korean heading anchors follow GitHub's rules (e.g. `## 7.1 목소리 샘플 녹음하기` → `#71-목소리-샘플-녹음하기`).
- **Never commit** anything in `voices/` (except `voices/.gitkeep`), `output/`, `.cache/` or `.venv/`. Check `git status` before committing and don't override `.gitignore` with `git add -f`.
- Keep `setuptools<81` in the chatterbox extras: Chatterbox's watermarker (resemble-perth) still imports `pkg_resources`.

## Notes

- Voice samples are the user's own recordings; only clone voices with permission, and don't strip Chatterbox's watermark.
- Not yet implemented (contributor ideas in README): CosyVoice2 engine, per-line voice switching, more languages in auto-detection.
