import json

import pytest

import config


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def files(tmp_path):
    chars = tmp_path / "characters"
    chars.mkdir()
    voice = {"speaker": 3, "speed": 1.2, "pitch": 0.0, "intonation": 1.0}
    write(chars / "saru.json", {"name": "サル", "intro": "あなたはサル。", "voice": voice})
    write(chars / "miku.json", {"name": "ミク", "intro": "あなたはミク。", "voice": {**voice, "speaker": 8}})
    (tmp_path / "persona.txt").write_text("短く答える。\n", encoding="utf-8")
    write(tmp_path / "config.json", {"character": "saru", "voicevox_url": "http://127.0.0.1:50021"})
    return tmp_path


def load(files):
    settings = config.load_config(files / "config.json", files / "config.local.json")
    return settings, config.load_character(settings, files / "characters", files / "persona.txt")


def test_defaults_without_a_local_file(files):
    settings, character = load(files)
    assert settings["voicevox_url"] == "http://127.0.0.1:50021"
    assert character.name == "サル"
    assert character.persona == "あなたはサル。\n\n短く答える。"
    assert character.voice == config.Voice(speaker=3, speed=1.2, pitch=0.0, intonation=1.0)


def test_local_file_switches_the_character_and_tunes_its_voice(files):
    write(files / "config.local.json", {"character": "miku", "voice": {"pitch": 0.05}})
    settings, character = load(files)
    assert settings["voicevox_url"] == "http://127.0.0.1:50021"
    assert character.name == "ミク"
    assert character.persona.startswith("あなたはミク。")
    assert character.voice == config.Voice(speaker=8, speed=1.2, pitch=0.05, intonation=1.0)


def test_unknown_character_names_the_choices(files):
    write(files / "config.local.json", {"character": "mei"})
    with pytest.raises(SystemExit, match="miku, saru"):
        load(files)


def test_merge_is_deep_and_later_wins():
    assert config.merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}}, None) == {"a": {"x": 1, "y": 3}, "b": 1}
