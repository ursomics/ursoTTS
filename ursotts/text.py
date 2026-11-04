"""Script parsing: comments, directives, pause tags, per-sentence language
detection (English / Korean), pronunciation fixes and chunking."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

HANGUL = re.compile(r"[\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")
LATIN = re.compile(r"[A-Za-z]")
PAUSE_TAG = re.compile(r"\[pause(?:\s+(\d+(?:\.\d+)?))?\]", re.IGNORECASE)
SENT_SPLIT = re.compile(r"(?<=[.!?…。！？])\s+")
DIRECTIVE = re.compile(r"^@(\w+)\s+(.+)$")


@dataclass
class Speech:
    text: str                      # what the model speaks (pronunciations applied)
    lang: str                      # language code, e.g. "en" / "ko"
    sentences: list[str] = field(default_factory=list)  # original text, for subtitles


@dataclass
class Pause:
    seconds: float


def detect_lang(text: str, default: str = "en") -> str:
    """Korean if Hangul makes up >= 25% of letters, else English.
    Handles Korean sentences that contain English terms (e.g. 'scRNA-seq 데이터')."""
    h, l = len(HANGUL.findall(text)), len(LATIN.findall(text))
    if h + l == 0:
        return default
    return "ko" if h / (h + l) >= 0.25 else "en"


# Word edges are Latin letters/digits only, so Korean particles attached to a
# term still match: 'DNA를', 'RNA-seq을'.
EDGE_L, EDGE_R = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
ACRONYM = re.compile(EDGE_L + r"[A-Z]{2,6}" + EDGE_R)  # all-caps word, 2-6 letters
# How Korean speakers name each Latin letter (DNA -> 디엔에이).
KO_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
    "에이", "비", "씨", "디", "이", "에프", "지", "에이치", "아이", "제이", "케이", "엘", "엠",
    "엔", "오", "피", "큐", "알", "에스", "티", "유", "브이", "더블유", "엑스", "와이", "제트"]))
# English letter names, used by the web UI to suggest syllable spellings.
LETTER_NAMES = {
    "A": "ay", "B": "bee", "C": "see", "D": "dee", "E": "ee", "F": "ef", "G": "jee",
    "H": "aych", "I": "eye", "J": "jay", "K": "kay", "L": "el", "M": "em", "N": "en",
    "O": "oh", "P": "pee", "Q": "kyoo", "R": "ar", "S": "ess", "T": "tee", "U": "yoo",
    "V": "vee", "W": "dubbelyoo", "X": "ex", "Y": "why", "Z": "zee",
}
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
         "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(digits: str) -> str:
    n = int(digits)
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else "-" + _ONES[n % 10])
    return " ".join(_ONES[int(d)] for d in digits)  # 101 -> one zero one


def dot_letters(letters: str) -> str:
    """'RNA' -> 'R.N.A.': each capital letter followed by a dot, read letter by letter."""
    return "".join(c + "." for c in letters)


def spell_acronyms(text: str, lang: str = "en") -> str:
    """Spell all-caps words so they are said letter by letter, smoothly.
    English: each letter followed by a dot ('DNA' -> 'D.N.A.'); no extra dot is added
    when the word already ends a sentence ('the DNA.' -> 'the D.N.A.').
    Korean: Hangul letter names ('DNA' -> '디엔에이'), since Latin letters in a
    Korean sentence sound unnatural. Runs after the pronunciation table, so a
    table entry (e.g. 'NANOG: NAN.og') always wins. Other languages: unchanged."""
    if lang == "en":
        def en(m):
            spelled = dot_letters(m.group(0))
            nxt = m.string[m.end():m.end() + 1]
            return spelled[:-1] if nxt == "." else spelled
        return ACRONYM.sub(en, text)
    if lang == "ko":
        return ACRONYM.sub(lambda m: "".join(KO_LETTERS[c] for c in m.group(0)), text)
    return text


SYLLABLE_MARK = re.compile(r"(?<=\w)[.·](?=\w)")


def is_letter_token(token: str) -> bool:
    """True for spelled-out letters: single capitals each followed by a dot,
    optionally ending in a plural s ('R.N.A.', 'C.D.', 'T.C.R.s')."""
    core = token[:-1] if token.endswith("s") and token[:-1].endswith(".") else token
    parts = core.rstrip(".").split(".")
    return core.endswith(".") and len(parts) >= 1 and all(len(x) == 1 and x.isupper() for x in parts)


def render_say(say: str) -> str:
    """Turn a dictionary spelling into what the voice reads.

    - Spelled letters stay exactly as written: 'R.N.A.' is read R, N, A.
    - Syllables joined by dots become one smooth word: 'NAN.og' -> 'nanog'.
    - In a spelling that uses either kind of dot, the other words are lowercased
      ('GAH.tah THREE' -> 'gahtah three', 'C.D. EIGHT' -> 'C.D. eight') so the
      voice doesn't spell them out. CAPS in syllables only mark stress for the reader.
    - A spelling without dots is returned exactly as typed ('Ursomics')."""
    say = str(say)
    tokens = say.split(" ")
    if not any(is_letter_token(t) or SYLLABLE_MARK.search(t) for t in tokens):
        return say
    out = []
    for t in tokens:
        if is_letter_token(t):
            out.append(t)
        else:
            out.append(SYLLABLE_MARK.sub("", t).lower())
    return " ".join(out)


def rule_text(rule) -> str:
    """A dictionary value is either 'respelling' or {say: ..., like: ...}."""
    if isinstance(rule, dict):
        return render_say(rule.get("say", ""))
    return render_say(rule)


def apply_pronunciations(text: str, lang: str, table: dict) -> str:
    """Whole-word replacements from the pronunciation table ('all' + language)."""
    rules = {**(table.get("all") or {}), **(table.get(lang) or {})}
    for src in sorted(rules, key=len, reverse=True):
        dst = rule_text(rules[src])
        if not dst:
            continue
        def repl(m, dst=dst):  # avoid "Q.P.C.R.." when the term ends a sentence
            return dst[:-1] if dst.endswith(".") and m.string[m.end():m.end() + 1] == "." else dst
        text = re.sub(EDGE_L + re.escape(str(src)) + EDGE_R, repl, text)
    return text


def _split_long(sentence: str, max_chars: int) -> list[str]:
    """Split an over-long sentence at commas/semicolons, then at spaces."""
    if len(sentence) <= max_chars:
        return [sentence]
    out, cur = [], ""
    for part in re.split(r"(?<=[,;:])\s+", sentence):
        while len(part) > max_chars:
            cut = part.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if cur:
                out.append(cur)
                cur = ""
            out.append(part[:cut].strip())
            part = part[cut:].strip()
        if cur and len(cur) + 1 + len(part) > max_chars:
            out.append(cur)
            cur = part
        else:
            cur = f"{cur} {part}".strip()
    if cur:
        out.append(cur)
    return out


def _speak(sentence: str, lang: str, pron: dict, spell: bool) -> str:
    text = apply_pronunciations(sentence, lang, pron)
    return spell_acronyms(text, lang) if spell else text


def _chunk(text, lang_mode, default_lang, max_chars, pron, sentence_pause, spell=True):
    sentences = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    sentences = [sub for s in sentences for sub in _split_long(s, max_chars)]

    groups: list[tuple[str, list[str]]] = []
    for s in sentences:
        lang = detect_lang(s, default_lang) if lang_mode == "auto" else lang_mode
        if groups:
            g_lang, g_sents = groups[-1]
            if g_lang == lang and len(" ".join(g_sents + [s])) <= max_chars:
                g_sents.append(s)
                continue
        groups.append((lang, [s]))

    items: list = []
    for i, (lang, sents) in enumerate(groups):
        if i:
            items.append(Pause(sentence_pause))
        spoken = " ".join(_speak(s, lang, pron, spell) for s in sents)
        items.append(Speech(spoken, lang, sents))
    return items


def parse_script(raw: str, *, default_lang="en", lang_mode="auto", max_chars=250,
                 sentence_pause=0.25, paragraph_pause=0.7, pronunciations=None,
                 spell_acronyms=True):
    """Turn a narration script into a list of Speech / Pause items.

    Script format:
      # comment lines are skipped
      @lang ko        directive: force a language for the whole file (or 'auto')
      [pause 1.5]     inline pause in seconds ([pause] = 1 s)
      blank line      paragraph break (longer pause)
    """
    pron = pronunciations or {}
    directives: dict[str, str] = {}
    body = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith("#"):
            continue
        m = DIRECTIVE.match(s)
        if m:
            directives[m.group(1).lower()] = m.group(2).strip()
            continue
        body.append(line)
    lang_mode = directives.get("lang", lang_mode)

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(body)) if p.strip()]
    items: list = []
    for pi, para in enumerate(paragraphs):
        para = " ".join(para.split())
        pos = 0
        for m in PAUSE_TAG.finditer(para):
            items += _chunk(para[pos:m.start()], lang_mode, default_lang, max_chars,
                            pron, sentence_pause, spell_acronyms)
            items.append(Pause(float(m.group(1) or 1.0)))
            pos = m.end()
        items += _chunk(para[pos:], lang_mode, default_lang, max_chars, pron,
                        sentence_pause, spell_acronyms)
        if pi < len(paragraphs) - 1:
            items.append(Pause(paragraph_pause))
    return items, directives
