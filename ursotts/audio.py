"""Audio helpers: silence, trimming, normalization, WAV/MP3 output, SRT subtitles."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def silence(seconds: float, sr: int) -> np.ndarray:
    return np.zeros(int(round(seconds * sr)), dtype=np.float32)


def trim(wav: np.ndarray, sr: int, threshold_db: float = -45.0, pad: float = 0.05) -> np.ndarray:
    """Cut leading/trailing near-silence so pauses between chunks stay consistent."""
    if wav.size == 0:
        return wav
    thr = 10 ** (threshold_db / 20) * max(float(np.abs(wav).max()), 1e-9)
    idx = np.where(np.abs(wav) > thr)[0]
    if idx.size == 0:
        return wav
    p = int(pad * sr)
    return wav[max(idx[0] - p, 0): min(idx[-1] + p + 1, wav.size)]


def peak_normalize(wav: np.ndarray, target_db: float = -1.0) -> np.ndarray:
    peak = float(np.abs(wav).max()) if wav.size else 0.0
    if peak < 1e-9:
        return wav
    return (wav * (10 ** (target_db / 20) / peak)).astype(np.float32)


def write_wav(path, wav: np.ndarray, sr: int) -> None:
    sf.write(str(path), np.clip(wav, -1, 1), sr, subtype="PCM_16")


def read_wav(path) -> tuple[np.ndarray, int]:
    wav, sr = sf.read(str(path), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    return wav, sr


def to_mp3(wav_path, mp3_path, loudnorm: bool = True) -> bool:
    """Export MP3 with ffmpeg; loudnorm targets YouTube's -14 LUFS."""
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    cmd = [ff, "-y", "-loglevel", "error", "-i", str(wav_path)]
    if loudnorm:
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11"]
    cmd += ["-codec:a", "libmp3lame", "-b:a", "192k", str(mp3_path)]
    subprocess.run(cmd, check=True)
    return True


def _ts(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, cues: list[tuple[float, float, str]]) -> None:
    lines = []
    for i, (a, b, text) in enumerate(cues, 1):
        lines += [str(i), f"{_ts(a)} --> {_ts(b)}", text, ""]
    Path(path).write_text("\n".join(lines), encoding="utf-8")
