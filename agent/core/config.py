"""core settings and the character the agent plays.

config.json holds the defaults (committed); config.local.json overrides them
per machine (gitignored, optional). The character is chosen by name from
characters/<name>.json and decides how the agent introduces itself and its
voice. persona.txt holds the rules every character shares.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from protocol import LISTEN_MODES

CORE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CORE_DIR / "config.json"
LOCAL_CONFIG_PATH = CORE_DIR / "config.local.json"
CHARACTERS_DIR = CORE_DIR / "characters"
RULES_PATH = CORE_DIR / "persona.txt"

ENGINES = ("voicevox", "openjtalk")


@dataclass
class Voice:
    """How a character speaks; speed, pitch and intonation mean what its engine makes of them."""

    engine: str  # one of ENGINES
    speed: float  # VOICEVOX speedScale / Open JTalk -r
    pitch: float  # VOICEVOX pitchScale / Open JTalk -fm (semitones); 0 keeps the voice's own pitch
    intonation: float  # VOICEVOX intonationScale / Open JTalk -jf
    speaker: int | None = None  # VOICEVOX only
    htsvoice: str | None = None  # Open JTalk only: path of the acoustic model


@dataclass
class Character:
    name: str  # shown next to its utterances
    persona: str  # system prompt: the character's introduction, then the shared rules
    voice: Voice
    wake_words: tuple[str, ...]  # calling one of these gets an answer in wake mode
    wake_reply: str | None  # said to a bare wake word in wake mode; None: no reply


def merge(*layers):
    """Later layers win, key by key inside nested objects."""
    merged = {}
    for layer in layers:
        for key, value in (layer or {}).items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = merge(merged[key], value)
            else:
                merged[key] = value
    return merged


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(path=CONFIG_PATH, local_path=LOCAL_CONFIG_PATH):
    local = _read(local_path) if local_path.exists() else None
    return merge(_read(path), local)


def listen_mode(config):
    """The configured listen mode; anything but a known one stops the start."""
    mode = config.get("listen_mode")
    if mode not in LISTEN_MODES:
        raise SystemExit(f"unknown listen_mode {mode!r} in config: choose one of {', '.join(LISTEN_MODES)}")
    return mode


def load_character(config, characters_dir=CHARACTERS_DIR, rules_path=RULES_PATH):
    """The configured character, with config["voice"] (if any) tuning its voice."""
    name = config["character"]
    path = characters_dir / f"{name}.json"
    if not path.exists():
        known = sorted(p.stem for p in characters_dir.glob("*.json"))
        raise SystemExit(f"unknown character {name!r} in config: choose one of {', '.join(known)}")
    data = _read(path)
    voice = merge(data["voice"], config.get("voice"))
    engine = voice.get("engine")
    if engine not in ENGINES:
        raise SystemExit(f"unknown voice.engine {engine!r} for {name!r}: choose one of {', '.join(ENGINES)}")
    rules = rules_path.read_text(encoding="utf-8").strip()
    return Character(
        name=data["name"],
        persona=f"{data['intro'].strip()}\n\n{rules}",
        wake_words=tuple(data["wake_words"]),
        wake_reply=data.get("wake_reply") or None,
        voice=Voice(
            engine=engine,
            speed=float(voice["speed"]),
            pitch=float(voice["pitch"]),
            intonation=float(voice["intonation"]),
            speaker=int(voice["speaker"]) if engine == "voicevox" else None,
            htsvoice=os.path.expanduser(voice["htsvoice"]) if engine == "openjtalk" else None,
        ),
    )
