"""Web interface: `ursotts ui` opens it at http://127.0.0.1:7860

Speak tab  - paste text, pick a voice (saved samples or record/upload one),
             adjust the speaking style, get narration + subtitles.
Batch tab  - render a whole folder of scripts, same as `ursotts batch`.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

import gradio as gr
import yaml

from . import audio
from .pipeline import Synthesizer, missing_voices, plan_batch, process_file, run_batch
from .text import KO_LETTERS, LETTER_NAMES, Speech, number_words, render_say

MAX_CANDIDATES = 6


def letters_notation(letters: str) -> str:
    """'DNA' -> 'dee.en.AY' (syllable notation, stress on the last letter)."""
    names = [LETTER_NAMES[c] for c in letters.upper()]
    names[-1] = names[-1].upper()
    return ".".join(names)


def _dot_letters(t: str) -> str:
    """'PD-L1' -> 'P.D.L. one', 'RNA-seq' -> 'R.N.A. seek', 'TCRs' -> 'T.C.R.s'."""
    t = re.sub(r"(?<=[A-Z])-(?=[A-Z0-9])", "", t)
    t = re.sub(r"\b([A-Z]{1,6})(s?)(\d*)\b",
               lambda m: "".join(c + "." for c in m.group(1)) + m.group(2)
               + (" " + number_words(m.group(3)) if m.group(3) else ""), t)
    return re.sub(r"-seq\b", " seek", t)


def _hangul_letters(t: str) -> str:
    """'PD-L1' -> '피디엘원', 'TCRs' -> '티씨알스': capital letters (and the digits and
    plural s attached to them) as Korean letter names. Ordinary words stay as typed."""
    ko_digits = dict(zip("0123456789", ["제로", "원", "투", "쓰리", "포", "파이브", "식스",
                                        "세븐", "에잇", "나인"]))
    t = re.sub(r"(?<=[A-Z])-(?=[A-Z0-9])", "", t)
    t = re.sub(r"-seq\b", " 시퀀싱", t)

    def conv(m):
        caps, plural, digits = m.group(1), m.group(2), m.group(3)
        return ("".join(KO_LETTERS[c] for c in caps) + ("스" if plural else "")
                + "".join(ko_digits[d] for d in digits))
    return re.sub(r"(?<![A-Za-z])([A-Z]{2,}|[A-Z](?=\d))(s?)(\d*)(?![a-z])", conv, t)


AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
SKIP_DIRS = {".venv", "venv", ".git", ".cache", "__pycache__", "node_modules", "docs", "ursotts"}


def prepare_sample(path: str, out_dir: Path) -> str:
    """Make any recording or upload safe for the voice model: mono, 24 kHz WAV,
    silence trimmed, volume evened out, at most 20 seconds. Browser recordings and compressed files (m4a, mp3, webm)
    can otherwise make the model stall without an error."""
    import hashlib
    import shutil
    import subprocess
    src = Path(path)
    if not src.exists():
        raise gr.Error("The voice sample could not be read. Please record or upload it again.")
    out_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
    dst = out_dir / f"sample_{digest}_v2.wav"
    if not dst.exists():
        ff = shutil.which("ffmpeg")
        if ff:
            try:
                # mono 24 kHz; trim silence at both ends; even out the volume; max 20 s
                clean = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
                         "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,"
                         "areverse,loudnorm=I=-20:TP=-2")
                subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src), "-af", clean,
                                "-ac", "1", "-ar", "24000", "-t", "20", str(dst)],
                               check=True, timeout=60)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                raise gr.Error("This audio file could not be converted. Try a WAV or MP3 file.")
        elif src.suffix.lower() in {".wav", ".flac"}:
            wav, sr = audio.read_wav(src)
            audio.write_wav(dst, wav[: sr * 30], sr)
        else:
            raise gr.Error("Install ffmpeg to use this file type, or upload a WAV file.")
    seconds = len(audio.read_wav(dst)[0]) / audio.read_wav(dst)[1]
    if seconds < 3:
        raise gr.Error(f"The sample is only {seconds:.1f} s long. Record 10–30 seconds of speech.")
    return str(dst)


def list_folders(root: Path, need_scripts: bool = False, depth: int = 3) -> list[str]:
    """Folders under the project (relative paths), skipping hidden and system folders.
    With need_scripts=True, only folders that contain .txt or .md scripts."""
    found = []
    def walk(d: Path, level: int):
        for c in sorted(d.iterdir()) if d.is_dir() else []:
            if not c.is_dir() or c.name.startswith(".") or c.name in SKIP_DIRS:
                continue
            rel = c.relative_to(root).as_posix()
            has = any(f.suffix.lower() in {".txt", ".md"} for f in c.iterdir() if f.is_file())
            if not need_scripts or has:
                found.append(rel)
            if level < depth:
                walk(c, level + 1)
    walk(root, 1)
    return found


def suggest_spellings(term: str, cfg: dict, lang: str = "en") -> list[str]:
    """A few versions worth comparing by ear, starting with the project's default style."""
    t = term.strip()
    if not t:
        return []
    if lang == "ko":
        out = [_hangul_letters(t), t]
    else:
        m = re.fullmatch(r"([A-Z]{2,6})(\d{0,3})", t)
        num = (" " + number_words(m.group(2))) if m and m.group(2) else ""
        if m and len(m.group(1)) >= 3 and m.group(1)[1] in "AEIOU":
            # gene-name rule: 2nd letter a vowel -> try it as a word first, letters second
            out = [m.group(1).capitalize() + num, _dot_letters(t), t]
        else:
            out = [_dot_letters(t), t]
        if m:
            out.append(letters_notation(m.group(1)) + num.upper())
        elif t.isalpha() and t[1:].islower():  # an ordinary word such as Ursomics
            out.append(re.sub(r"(?<=[^aeiou\W])o(?=[^aeiou\W])", ".OH.", t.lower(),
                              count=1).strip("."))
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq[:MAX_CANDIDATES]


YAML_PLAIN = re.compile(r"^[A-Za-z0-9][\w.+\-]*( [\w.+\-]+)*$")


def _yaml_scalar(text: str) -> str:
    return text if YAML_PLAIN.match(text) and text.lower() not in {"yes", "no", "on", "off", "true", "false", "null"} \
        else '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def upsert_pronunciation(path: Path, lang: str, term: str, say: str, like: str = "") -> None:
    """Add or replace one entry in pronunciations.yaml, keeping every comment."""
    value = _yaml_scalar(say)
    if like.strip():
        value = "{say: %s, like: %s}" % (_yaml_scalar(say), '"' + like.strip().replace('"', "'") + '"')
    entry = f"  {_yaml_scalar(term)}: {value}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    head = next((i for i, l in enumerate(lines) if re.match(rf"^{lang}:\s*(\{{\s*\}})?\s*(#.*)?$", l)), None)
    if head is None:
        lines += ["", f"{lang}:", entry]
    else:
        lines[head] = f"{lang}:"
        end = head + 1
        while end < len(lines) and (lines[end].startswith(" ") or not lines[end].strip()):
            end += 1
        key_re = re.compile(rf"^\s+[\"']?{re.escape(term)}[\"']?\s*:")
        hit = next((i for i in range(head + 1, end) if key_re.match(lines[i])), None)
        if hit is not None:
            lines[hit] = entry
        else:
            last = max((i for i in range(head + 1, end) if lines[i].strip()), default=head)
            lines.insert(last + 1, entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ursoTTS brand palette (see docs/brand/color_palette.png)
CORAL, DEEP_CORAL, SOFT_CORAL = "#D97757", "#C4623F", "#F0C9B8"
INK, WHITE, CREAM = "#1B1B1B", "#FFFFFF", "#F6EFE6"
# derived neutrals for borders and secondary text
LINE_LIGHT, MUTED_LIGHT = "#E6D9C8", "#6E6259"
SURFACE_DARK, LINE_DARK, MUTED_DARK = "#262220", "#3A332F", "#BFB3A8"

ASSETS = Path(__file__).parent / "assets"
YOUTUBE, WEBSITE, GITHUB = "https://youtube.com/@ursomics", "https://ursomics.com", "https://github.com/ursomics"
FAVICON = ASSETS / "favicon.png"


def _logo_data_uri() -> str:
    import base64
    try:
        return "data:image/png;base64," + base64.b64encode((ASSETS / "logo.png").read_bytes()).decode()
    except OSError:
        return ""


GRADIO_6 = int(gr.__version__.split(".")[0]) >= 6
LANGS = {"Auto (English + Korean)": "auto", "English": "en", "Korean": "ko"}
CONFIG_VOICES = "My saved voices"
OWN_VOICE = "Record or upload a new sample"

HEADER = f"""
<div class="urso-head">
  <img class="urso-logo" src="{_logo_data_uri()}" alt="ursoTTS">
  <div>
    <div class="urso-mark"><span class="urso-a">urso</span><span class="urso-b">TTS</span></div>
    <div class="urso-tag">VOICE CLONING · TEXT-TO-SPEECH</div>
    <div class="urso-sub">Your own voice, on repeat.</div>
  </div>
</div>
"""

CSS = f"""
html {{ overflow-y: scroll; scrollbar-gutter: stable; }}
.gradio-container {{ width: 100% !important; max-width: 1120px !important; margin: 0 auto; }}
[role=tabpanel] {{ width: 100%; }}
.urso-head {{ display: flex; align-items: center; gap: 20px; padding: 24px 4px 12px; }}
.urso-logo {{ width: 84px; height: 84px; object-fit: contain; flex: none; }}
.urso-mark {{ font-family: Poppins, system-ui, sans-serif; font-size: 2.6rem; line-height: 1;
              letter-spacing: -0.01em; }}
.urso-a {{ font-weight: 700; color: {INK}; }}
.urso-b {{ font-weight: 800; color: {CORAL}; }}
.urso-tag {{ font-family: Poppins, system-ui, sans-serif; font-weight: 600; font-size: 0.8rem;
             letter-spacing: 0.12em; color: {DEEP_CORAL}; margin-top: 8px; }}
.urso-sub {{ color: {MUTED_LIGHT}; font-size: 0.95rem; margin-top: 4px; }}
.urso-note {{ color: {MUTED_LIGHT}; font-size: 0.85rem; }}
.urso-group-title {{ padding: 10px 12px 0; }}
.urso-foot {{ color: {MUTED_LIGHT}; font-size: 0.85rem; text-align: center; padding: 18px 0 8px; line-height: 1.9; }}
.urso-credit img {{ display: inline-block !important; height: 20px !important; width: 20px !important;
                     vertical-align: -5px !important; margin: 0 2px !important; }}
.urso-credit a {{ color: {DEEP_CORAL}; text-decoration: none; font-weight: 600; }}
.urso-credit a:hover {{ text-decoration: underline; }}
.dark .urso-foot {{ color: {MUTED_DARK}; }}
.dark .urso-credit a {{ color: {CORAL}; }}
.dark .urso-a {{ color: {WHITE}; }}
.dark .urso-tag {{ color: {CORAL}; }}
.dark .urso-sub, .dark .urso-note {{ color: {MUTED_DARK}; }}
.tab-nav button.selected, button[role="tab"][aria-selected="true"] {{ color: {DEEP_CORAL} !important;
              border-color: {CORAL} !important; }}
.dark .tab-nav button.selected, .dark button[role="tab"][aria-selected="true"] {{ color: {CORAL} !important; }}
footer {{ display: none !important; }}
"""

SCRIPT_HINT = ("Paste your narration here.\n\n"
               "Blank line = paragraph pause. [pause 1.5] = pause in seconds. "
               "Lines starting with # are skipped.")


def _theme():
    """Cream page in light mode, ink page in dark mode; coral for actions."""
    return gr.themes.Base(
        primary_hue=gr.themes.colors.orange, neutral_hue=gr.themes.colors.stone,
        font=[gr.themes.GoogleFont("Poppins"), "system-ui", "sans-serif"],
        radius_size=gr.themes.sizes.radius_md,
    ).set(
        body_background_fill=CREAM, body_background_fill_dark=INK,
        background_fill_primary=WHITE, background_fill_primary_dark=SURFACE_DARK,
        background_fill_secondary=CREAM, background_fill_secondary_dark=INK,
        body_text_color=INK, body_text_color_dark=CREAM,
        body_text_color_subdued=MUTED_LIGHT, body_text_color_subdued_dark=MUTED_DARK,
        block_background_fill=WHITE, block_background_fill_dark=SURFACE_DARK,
        block_border_color=LINE_LIGHT, block_border_color_dark=LINE_DARK,
        border_color_primary=LINE_LIGHT, border_color_primary_dark=LINE_DARK,
        block_label_text_color=MUTED_LIGHT, block_label_text_color_dark=MUTED_DARK,
        block_title_text_color=INK, block_title_text_color_dark=CREAM,
        input_background_fill=WHITE, input_background_fill_dark=INK,
        input_border_color=LINE_LIGHT, input_border_color_dark=LINE_DARK,
        input_border_color_focus=CORAL, input_border_color_focus_dark=CORAL,
        button_primary_background_fill=CORAL, button_primary_background_fill_dark=CORAL,
        button_primary_background_fill_hover=DEEP_CORAL,
        button_primary_background_fill_hover_dark=DEEP_CORAL,
        button_primary_text_color=WHITE, button_primary_text_color_dark=WHITE,
        button_secondary_background_fill=SOFT_CORAL, button_secondary_background_fill_dark=LINE_DARK,
        button_secondary_background_fill_hover="#EBB8A3",
        button_secondary_background_fill_hover_dark="#4A413C",
        button_secondary_text_color=INK, button_secondary_text_color_dark=CREAM,
        slider_color=CORAL, slider_color_dark=CORAL,
        checkbox_background_color_selected=CORAL, checkbox_background_color_selected_dark=CORAL,
        checkbox_label_background_fill=CREAM, checkbox_label_background_fill_dark=INK,
        checkbox_label_background_fill_hover="#F3E4D7", checkbox_label_background_fill_hover_dark="#2E2825",
        checkbox_label_background_fill_selected=SOFT_CORAL,
        checkbox_label_background_fill_selected_dark="#4A3229",
        checkbox_label_border_color=LINE_LIGHT, checkbox_label_border_color_dark=LINE_DARK,
        color_accent=CORAL, color_accent_soft=SOFT_CORAL, color_accent_soft_dark=LINE_DARK,
    )


def build_app(cfg: dict) -> gr.Blocks:
    out_root = Path(cfg.get("ui_output", "output"))
    shared: dict = {"synth": None}

    def get_synth() -> Synthesizer:
        if shared["synth"] is None:
            from .engine import make_engine
            t0 = time.time()
            shared["synth"] = Synthesizer(cfg, make_engine(cfg))
            shared["load_time"] = time.time() - t0
            print(f"[ursotts] voice model ready in {shared['load_time']:.1f} s")
        return shared["synth"]

    def apply_settings(exag, cfgw, temp, seed) -> Synthesizer:
        seed = None if seed in (None, "") else int(seed)
        gen = dict(exaggeration=exag, cfg_weight=cfgw, temperature=temp, seed=seed)
        cfg["generation"].update(gen)
        synth = get_synth()
        synth.engine.update(**gen)
        return synth

    root = Path.cwd()
    configured = cfg["voices"] or {}
    voices_dir = (Path(next(iter(configured.values()))).parent if configured
                  else (root / "voices"))

    def voice_choices():
        files = sorted(f for f in voices_dir.glob("*") if f.suffix.lower() in AUDIO_EXTS) \
            if voices_dir.is_dir() else []
        return [(f.name, str(f)) for f in files]

    def default_voice(lang):
        v = configured.get(lang)
        return v if v and Path(v).exists() else next((c[1] for c in voice_choices()), None)

    def refresh_voices(en, ko):
        ch = voice_choices()
        vals = [c[1] for c in ch]
        return (gr.update(choices=ch, value=en if en in vals else default_voice("en")),
                gr.update(choices=ch, value=ko if ko in vals else default_voice("ko")))

    def speak(text, lang, voice_mode, voice_en, voice_ko, own_voice, exag, cfgw, temp, seed):
        if not (text or "").strip():
            raise gr.Error("Type or paste some text first.")
        synth_voice, overrides = None, {}
        if voice_mode == OWN_VOICE:
            if not own_voice:
                raise gr.Error("Record or upload a voice sample first, or choose My saved voices.")
            synth_voice = prepare_sample(own_voice, out_root / "ui" / "samples")
        else:
            overrides = {k: v for k, v in {"en": voice_en, "ko": voice_ko}.items()
                         if v and Path(v).exists()}
            if not overrides and cfg["engine"] != "dummy":
                raise gr.Error("No saved voice found. Put a WAV or MP3 sample in the voices "
                               "folder, or record one with Record or upload a new sample.")
        synth = apply_settings(exag, cfgw, temp, seed)
        synth.voice_override, synth.voice_overrides = synth_voice, overrides
        run_cfg = {**cfg, "lang_mode": LANGS[lang]}

        out_dir = out_root / "ui"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("ui_%Y%m%d_%H%M%S")
        src = out_dir / f"{stem}.txt"
        src.write_text(text, encoding="utf-8")
        try:
            r = process_file(src, out_dir, synth, run_cfg, log=lambda *_: None)
        finally:
            synth.voice_override, synth.voice_overrides = None, {}
        files = [str(p) for p in (out_dir / f"{stem}{ext}" for ext in (".wav", ".mp3", ".srt", ".txt"))
                 if p.exists()]
        note = (f"Made **{r['seconds']} s** of audio in {r['render_time']} s. "
                f"Saved in `{out_dir}/` as `{stem}`.")
        if shared.pop("load_time", None) is not None:
            note += " (First run: the voice model was loaded, so this one took longer.)"
        return files[0], files, note

    def save_sample(own_voice, name, en, ko):
        if not own_voice:
            raise gr.Error("Record or upload a voice sample first.")
        safe = re.sub(r"[^\w\-]+", "_", (name or "").strip()).strip("_")
        if not safe:
            raise gr.Error("Type a name for this voice, for example my_voice_en.")
        prepared = prepare_sample(own_voice, out_root / "ui" / "samples")
        voices_dir.mkdir(parents=True, exist_ok=True)
        target = voices_dir / f"{safe}.wav"
        target.write_bytes(Path(prepared).read_bytes())
        u_en, u_ko = refresh_voices(en, ko)
        return u_en, u_ko, f"Saved as **{target.name}** in your voices folder. Choose it under My saved voices."

    def folder_updates(src_value, out_value):
        sf, of = list_folders(root, need_scripts=True), list_folders(root)
        return (gr.update(choices=sf, value=src_value if src_value else (sf[0] if sf else None)),
                gr.update(choices=of, value=out_value))

    def show_scripts(folder):
        d = root / (folder or "")
        if not folder or not d.is_dir():
            return "*Choose a scripts folder.*"
        names = sorted(f.name for f in d.iterdir() if f.suffix.lower() in {".txt", ".md"})
        if not names:
            return f"No .txt or .md scripts in `{folder}/`."
        shown = ", ".join(f"`{n}`" for n in names[:12]) + (" …" if len(names) > 12 else "")
        return f"**{len(names)} script(s)** in `{folder}/`: {shown}"

    def create_folder(new_name, src_value):
        rel = (new_name or "").strip().strip("/")
        if not rel or rel.startswith("~") or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise gr.Error("Type a folder name inside this project, for example output/episode1.")
        (root / rel).mkdir(parents=True, exist_ok=True)
        u_src, u_out = folder_updates(src_value, rel)
        return u_src, u_out, gr.update(value=""), f"Created `{rel}/`."

    def batch(src, out, force):
        src_p, out_p = Path((src or "").strip() or "scripts"), Path((out or "").strip() or "output")
        if not src_p.exists():
            raise gr.Error(f"Folder not found: {src_p}")
        files, todo, keys = plan_batch(cfg, src_p, out_p, force)
        if not files:
            return f"No .txt or .md scripts found in {src_p}/."
        if not todo:
            return (f"All {len(files)} scripts are up to date. "
                    "Tick “Render everything again” to redo them.")
        if missing_voices(cfg):
            raise gr.Error("Voice sample not found: " + ", ".join(Path(m).name for m in missing_voices(cfg)))
        synth = get_synth()
        synth.voice_override, synth.voice_overrides = None, {}
        lines: list[str] = []
        results = run_batch(cfg, synth, todo, out_p, keys, log=lines.append)
        ok = sum("error" not in r for r in results)
        skipped = len(files) - len(todo)
        lines.append(f"\nRendered {ok} of {len(todo)} scripts"
                     + (f", skipped {skipped} unchanged" if skipped else "")
                     + f". Files are in {out_p}/.")
        return "\n".join(lines)

    def lab_suggest(term, lang_label):
        if not term.strip():
            raise gr.Error("Type a word first, for example DNA or Ursomics.")
        lang = "ko" if lang_label == "Korean" else "en"
        return "\n".join(suggest_spellings(term, cfg, lang))

    def lab_listen(term, lang_label, context, candidates):
        cands = [c.strip() for c in (candidates or "").splitlines() if c.strip()][:MAX_CANDIDATES]
        if not cands:
            raise gr.Error("Add at least one spelling (one per line), or click Suggest spellings.")
        if missing_voices(cfg):
            raise gr.Error("Voice sample not found: " + ", ".join(missing_voices(cfg)))
        lang = "ko" if lang_label == "Korean" else "en"
        context = context if "{word}" in (context or "") else "{word}"
        synth = get_synth()
        synth.voice_override = None
        lab = out_root / "ui" / "pronunciation"
        lab.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"\W+", "_", term.strip()) or "word"
        players = []
        for i in range(MAX_CANDIDATES):
            if i < len(cands):
                sentence = context.replace("{word}", render_say(cands[i]))
                wav = audio.peak_normalize(synth.chunk_audio(Speech(sentence, lang, [sentence])))
                path = lab / f"{slug}_{i + 1}.wav"
                audio.write_wav(path, wav, synth.sr)
                players.append(gr.update(value=str(path), label=f"{i + 1}. {cands[i]}", visible=True))
            else:
                players.append(gr.update(value=None, visible=False))
        pick = gr.update(choices=[f"{i + 1}. {c}" for i, c in enumerate(cands)], value=None)
        return [*players, pick]

    def lab_save(term, lang_label, choice, like):
        if not choice:
            raise gr.Error("Choose the version that sounded best.")
        term = term.strip()
        spelling = choice.split(". ", 1)[1]
        lang = "ko" if lang_label == "Korean" else "en"
        path = Path(cfg.get("pronunciations_path") or "pronunciations.yaml")
        upsert_pronunciation(path, lang, term, spelling, like or "")
        cfg["pronunciation_table"] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return (f"Saved: **{term}** → `{spelling}` (voice reads “{render_say(spelling)}”). "
                "Scripts that use it are re-rendered on the next batch.")

    g = cfg["generation"]
    style = {} if GRADIO_6 else {"theme": _theme(), "css": CSS}
    with gr.Blocks(title="ursoTTS", **style) as app:
        gr.HTML(HEADER)
        with gr.Tabs():
            with gr.Tab("Speak"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=3):
                        text = gr.Textbox(label="Script", lines=10, placeholder=SCRIPT_HINT, elem_id="speak-script")
                        with gr.Row():
                            lang = gr.Dropdown(list(LANGS), value="Auto (English + Korean)",
                                               label="Language", elem_id="speak-lang")
                            voice_mode = gr.Radio([CONFIG_VOICES, OWN_VOICE], value=CONFIG_VOICES,
                                                  label="Voice", elem_id="speak-voice")
                        with gr.Group(visible=True, elem_id="speak-saved") as saved_box:
                            with gr.Row(equal_height=True):
                                voice_en = gr.Dropdown(voice_choices(), value=default_voice("en"),
                                                       label="English voice", scale=4)
                                voice_ko = gr.Dropdown(voice_choices(), value=default_voice("ko"),
                                                       label="Korean voice", scale=4)
                                refresh_v = gr.Button("↻ Refresh", scale=1, min_width=90)
                        with gr.Group(visible=False, elem_id="speak-own-voice") as own_box:
                            own_voice = gr.Audio(sources=["microphone", "upload"], type="filepath",
                                                 format="wav",
                                                 label="Voice sample: 10–30 seconds of clear speech")
                            with gr.Row(equal_height=True):
                                sample_name = gr.Textbox(label="Keep this voice as", placeholder="my_voice_en",
                                                         scale=4)
                                save_v = gr.Button("Save to my voices", scale=2)
                            sample_note = gr.Markdown()
                        go = gr.Button("Generate narration", variant="primary", elem_id="speak-go")
                    with gr.Column(scale=2):
                        player = gr.Audio(label="Narration", type="filepath", interactive=False, elem_id="speak-player")
                        files = gr.File(label="Download", file_count="multiple", interactive=False, elem_id="speak-files")
                        note = gr.Markdown()
                        with gr.Accordion("Speaking style", open=False, elem_id="speak-style"):
                            exag = gr.Slider(0.25, 1.0, value=g["exaggeration"], step=0.05,
                                             label="Expressiveness",
                                             info="Lower is calm, higher is animated")
                            cfgw = gr.Slider(0.0, 1.0, value=g["cfg_weight"], step=0.05,
                                             label="Pacing",
                                             info="Lower is slower and more deliberate")
                            temp = gr.Slider(0.3, 1.2, value=g["temperature"], step=0.05,
                                             label="Variation")
                            seed = gr.Number(value=g.get("seed"), precision=0, label="Seed",
                                             info="Same seed gives the same take; change it for a new one")
                voice_mode.change(lambda m: (gr.update(visible=m != OWN_VOICE), gr.update(visible=m == OWN_VOICE)),
                                  voice_mode, [saved_box, own_box])
                refresh_v.click(refresh_voices, [voice_en, voice_ko], [voice_en, voice_ko])
                save_v.click(save_sample, [own_voice, sample_name, voice_en, voice_ko],
                             [voice_en, voice_ko, sample_note])
                go.click(speak, [text, lang, voice_mode, voice_en, voice_ko, own_voice, exag, cfgw, temp, seed],
                         [player, files, note])

            with gr.Tab("Pronunciation"):
                gr.Markdown("Find the spelling that makes a word sound right, then save it. "
                            "Each version is spoken inside the sentence below, in your voice. "
                            "Letters: each capital followed by a dot (R.N.A.). "
                            "Word-like sounds: syllables joined by dots (NAN.og), read as one word. "
                            "Korean: write the Hangul reading (피디엘원).", elem_classes="urso-note")
                with gr.Row():
                    term = gr.Textbox(label="Word or abbreviation", placeholder="DNA, RNA-seq, Ursomics", elem_id="pron-term")
                    lab_lang = gr.Dropdown(["English", "Korean"], value="English", label="Language", elem_id="pron-lang")
                context = gr.Textbox(value="Today we look at {word} in our data.",
                                     label="Test sentence", info="{word} is replaced by each spelling")
                candidates = gr.Textbox(lines=6, label="Versions to compare, one per line", elem_id="pron-candidates",
                                        placeholder="P.D.L. one\nPD-L1\nNAN.og")
                with gr.Row():
                    suggest_btn = gr.Button("Suggest spellings", elem_id="pron-suggest")
                    listen_btn = gr.Button("Listen to all", variant="primary", elem_id="pron-listen")
                with gr.Row(elem_id="pron-players"):
                    lab_players = [gr.Audio(type="filepath", interactive=False, visible=False)
                                   for _ in range(MAX_CANDIDATES)]
                pick = gr.Radio([], label="Best version", elem_id="pron-pick")
                like = gr.Textbox(label="Sounds like (optional note)",
                                  placeholder="NAN as in man, og as in dog")
                save_btn = gr.Button("Save to pronunciation rules", variant="primary", elem_id="pron-save")
                saved = gr.Markdown()
                suggest_btn.click(lab_suggest, [term, lab_lang], candidates)
                listen_btn.click(lab_listen, [term, lab_lang, context, candidates],
                                 [*lab_players, pick])
                save_btn.click(lab_save, [term, lab_lang, pick, like], saved)

            with gr.Tab("Batch"):
                gr.Markdown("Render every `.txt` and `.md` script in a folder. Scripts whose "
                            "text and settings haven't changed are skipped.",
                            elem_classes="urso-note")
                script_dirs = list_folders(root, need_scripts=True)
                with gr.Row(equal_height=True):
                    src = gr.Dropdown(script_dirs, value="scripts" if "scripts" in script_dirs
                                      else (script_dirs[0] if script_dirs else None),
                                      allow_custom_value=True, label="Scripts folder",
                                      info="Folders in this project that contain scripts",
                                      elem_id="batch-src", scale=5)
                    out = gr.Dropdown(list_folders(root), value="output", allow_custom_value=True,
                                      label="Output folder", info="Created automatically if it doesn't exist",
                                      elem_id="batch-out", scale=5)
                    refresh_f = gr.Button("↻ Refresh", scale=1, min_width=90)
                script_list = gr.Markdown(show_scripts(src.value), elem_classes="urso-note")
                with gr.Row(equal_height=True):
                    new_folder = gr.Textbox(label="New folder", placeholder="output/episode1", scale=5)
                    make_folder = gr.Button("Create folder", scale=2)
                folder_note = gr.Markdown()
                force = gr.Checkbox(label="Render everything again", elem_id="batch-force")
                run = gr.Button("Render all scripts", variant="primary", elem_id="batch-run")
                log = gr.Textbox(label="Progress", lines=14, interactive=False, elem_id="batch-log")
                src.change(show_scripts, src, script_list)
                refresh_f.click(folder_updates, [src, out], [src, out])
                make_folder.click(create_folder, [new_folder, src], [src, out, new_folder, folder_note])
                run.click(batch, [src, out, force], log)

        gr.HTML(f"""
<div class="urso-foot">
  <div>Only clone your own voice, or a voice you have permission to use.</div>
  <div class="urso-credit">Made with <img src="{_logo_data_uri()}" alt="ursoTTS bear"> by
    <a href="{GITHUB}" target="_blank" rel="noopener">ursomics@GitHub</a> ·
    <a href="{WEBSITE}" target="_blank" rel="noopener">ursomics.com</a> ·
    <a href="{YOUTUBE}" target="_blank" rel="noopener">@ursomics</a></div>
</div>
""")
    return app


def launch(cfg: dict, port: int = 7860, share: bool = False, open_browser: bool = True):
    app = build_app(cfg)
    kwargs = dict(server_name="127.0.0.1", server_port=port, share=share, inbrowser=open_browser)
    if FAVICON.exists():
        kwargs["favicon_path"] = str(FAVICON)
    if GRADIO_6:  # Gradio 6 moved theme/css from Blocks() to launch()
        kwargs.update(theme=_theme(), css=CSS)
    app.queue().launch(**kwargs)
