"""saru-core settings and the character the agent plays.

config.json holds the defaults (committed); config.local.json overrides them
per machine (gitignored, optional). The character is chosen by name from
characters/<name>.json and decides how the agent introduces itself and its
voice. persona.txt holds the rules every character shares.
"""

import json
from dataclasses import dataclass
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = CORE_DIR / "config.json"
LOCAL_CONFIG_PATH = CORE_DIR / "config.local.json"
CHARACTERS_DIR = CORE_DIR / "characters"
RULES_PATH = CORE_DIR / "persona.txt"


@dataclass
class Voice:
    speaker: int
    speed: float  # VOICEVOX speedScale
    pitch: float  # VOICEVOX pitchScale; 0 keeps the speaker's own pitch
    intonation: float  # VOICEVOX intonationScale


@dataclass
class Character:
    name: str  # shown next to its utterances
    persona: str  # system prompt: the character's introduction, then the shared rules
    voice: Voice


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


def load_character(config, characters_dir=CHARACTERS_DIR, rules_path=RULES_PATH):
    """The configured character, with config["voice"] (if any) tuning its voice."""
    name = config["character"]
    path = characters_dir / f"{name}.json"
    if not path.exists():
        known = sorted(p.stem for p in characters_dir.glob("*.json"))
        raise SystemExit(f"unknown character {name!r} in config: choose one of {', '.join(known)}")
    data = _read(path)
    voice = merge(data["voice"], config.get("voice"))
    rules = rules_path.read_text(encoding="utf-8").strip()
    return Character(
        name=data["name"],
        persona=f"{data['intro'].strip()}\n\n{rules}",
        voice=Voice(
            speaker=int(voice["speaker"]),
            speed=float(voice["speed"]),
            pitch=float(voice["pitch"]),
            intonation=float(voice["intonation"]),
        ),
    )
