"""Paths and small helpers shared by the wake word scripts."""

import io
import json
import os
import sys
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000

# Large downloads (negative features, noise, FLEURS). Not under / (too small on mouse).
DATA_DIR = Path(os.environ.get("WAKEWORD_DATA", "/mnt/shared/wakeword"))
# Synthesized clips, features and checkpoints.
WORK_DIR = Path(os.environ.get("WAKEWORD_WORK", Path.home() / "wakeword-work"))
# Same place as ReazonSpeech in agent/core/listen.py.
MODEL_PATH = Path.home() / ".cache" / "saru9000" / "models" / "wakeword" / "miku.onnx"

DOWNLOAD_DIR = DATA_DIR / "download"
RIR_DIR = DATA_DIR / "rir"
BACKGROUND_DIR = DATA_DIR / "background"
FLEURS_DIR = DATA_DIR / "fleurs"
ACAV_FEATURES = DOWNLOAD_DIR / "openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
VALIDATION_FEATURES = DOWNLOAD_DIR / "validation_set_features.npy"

CLIP_DIR = WORK_DIR / "clips"
FEATURE_DIR = WORK_DIR / "features"
# Recordings copied from vaio's ~/asr-bench (see README).
BENCH_DIR = WORK_DIR / "asr-bench"

# VOICEVOX styles used for the evaluation recordings (rec-1030-*: v2 v8 v11 v13 v14).
# Every style of those characters is kept out of training so the score is not
# a measure of memorized voices.
EVAL_CHARACTERS = {"四国めたん", "春日部つむぎ", "玄野武宏", "青山龍星", "冥鳴ひまり"}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def read_wav(path):
    """16 kHz mono wav (16-bit, or float as FLEURS ships) -> float32 in [-1, 1]."""
    import soundfile

    samples, rate = soundfile.read(str(path), dtype="float32")
    if rate != SAMPLE_RATE or samples.ndim != 1:
        raise ValueError(f"{path}: expected 16 kHz mono")
    return samples


def write_wav(path, samples):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.asarray(samples) * 32767, -32768, 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


class Voicevox:
    def __init__(self, url):
        self.url = url.rstrip("/")

    def _post(self, path, params, body=None):
        request = urllib.request.Request(
            f"{self.url}{path}?{urllib.parse.urlencode(params)}",
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    def talk_styles(self):
        """[(style_id, character)] for every talk style except the evaluation characters'."""
        with urllib.request.urlopen(f"{self.url}/speakers", timeout=30) as response:
            speakers = json.load(response)
        return [
            (style["id"], speaker["name"])
            for speaker in speakers
            if speaker["name"] not in EVAL_CHARACTERS
            for style in speaker["styles"]
            if style.get("type", "talk") == "talk"
        ]

    def query(self, text, style):
        return json.loads(self._post("/audio_query", {"text": text, "speaker": style}))

    def mora_pitch(self, accent_phrases, style):
        return json.loads(self._post("/mora_pitch", {"speaker": style}, accent_phrases))

    def synthesize(self, query, style):
        """float32 samples at 16 kHz."""
        query = dict(query, outputSamplingRate=SAMPLE_RATE, outputStereo=False)
        data = self._post("/synthesis", {"speaker": style}, query)
        with wave.open(io.BytesIO(data)) as w:
            pcm = w.readframes(w.getnframes())
        return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
