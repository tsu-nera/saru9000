import json
import os

import pytest

import config


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def files(tmp_path):
    chars = tmp_path / "characters"
    chars.mkdir()
    voice = {"engine": "voicevox", "speaker": 3, "speed": 1.2, "pitch": 0.0, "intonation": 1.0}
    write(chars / "saru.json", {"name": "サル", "intro": "あなたはサル。", "wake_words": ["サル", "猿"], "voice": voice})
    write(
        chars / "miku.json",
        {"name": "ミク", "intro": "あなたはミク。", "wake_words": ["ミク"], "voice": {**voice, "speaker": 8}},
    )
    (tmp_path / "persona.txt").write_text("短く答える。\n", encoding="utf-8")
    write(tmp_path / "config.json", {"character": "saru", "listen_mode": "wake", "voicevox_url": "http://127.0.0.1:50021"})
    return tmp_path


def load(files):
    settings = config.load_config(files / "config.json", files / "config.local.json")
    return settings, config.load_character(settings, files / "characters", files / "persona.txt")


def test_defaults_without_a_local_file(files):
    settings, character = load(files)
    assert settings["voicevox_url"] == "http://127.0.0.1:50021"
    assert character.name == "サル"
    assert character.wake_words == ("サル", "猿")
    assert character.wake_reply is None  # not set in the fixture: no reply
    assert config.listen_mode(settings) == "wake"
    assert character.persona == "あなたはサル。\n\n短く答える。"
    assert character.voice == config.Voice(engine="voicevox", speaker=3, speed=1.2, pitch=0.0, intonation=1.0)


def test_local_file_switches_the_character_and_tunes_its_voice(files):
    write(files / "config.local.json", {"character": "miku", "voice": {"pitch": 0.05}})
    settings, character = load(files)
    assert settings["voicevox_url"] == "http://127.0.0.1:50021"
    assert character.name == "ミク"
    assert character.persona.startswith("あなたはミク。")
    assert character.voice == config.Voice(engine="voicevox", speaker=8, speed=1.2, pitch=0.05, intonation=1.0)


def test_openjtalk_voice_expands_the_model_path(files):
    voice = {"engine": "openjtalk", "htsvoice": "~/voices/x.htsvoice", "speed": 1.0, "pitch": 2.0, "intonation": 1.5}
    write(
        files / "characters" / "miku.json",
        {"name": "ミク", "intro": "あなたはミク。", "wake_words": ["ミク"], "voice": voice},
    )
    write(files / "config.local.json", {"character": "miku"})
    _, character = load(files)
    assert character.voice == config.Voice(
        engine="openjtalk",
        speed=1.0,
        pitch=2.0,
        intonation=1.5,
        htsvoice=os.path.expanduser("~/voices/x.htsvoice"),
    )


def test_unknown_character_names_the_choices(files):
    write(files / "config.local.json", {"character": "mei"})
    with pytest.raises(SystemExit, match="miku, saru"):
        load(files)


@pytest.mark.parametrize("engine", ["coeiroink", None])
def test_unknown_engine_names_the_choices(files, engine):
    voice = {"speaker": 3, "speed": 1.2, "pitch": 0.0, "intonation": 1.0}
    if engine is not None:
        voice["engine"] = engine
    write(
        files / "characters" / "saru.json",
        {"name": "サル", "intro": "あなたはサル。", "wake_words": ["サル"], "voice": voice},
    )
    with pytest.raises(SystemExit, match="voicevox, openjtalk"):
        load(files)


@pytest.mark.parametrize("mode", ["always", "wake"])
def test_listen_mode_can_be_switched_by_the_local_file(files, mode):
    write(files / "config.local.json", {"listen_mode": mode})
    settings, _ = load(files)
    assert config.listen_mode(settings) == mode


@pytest.mark.parametrize("mode", ["sometimes", None])
def test_unknown_listen_mode_names_the_choices(files, mode):
    write(files / "config.local.json", {"listen_mode": mode})
    settings, _ = load(files)
    with pytest.raises(SystemExit, match="wake, always"):
        config.listen_mode(settings)


def test_committed_characters_load():
    settings = config.load_config(config.CONFIG_PATH, config.CONFIG_PATH.with_name("none.json"))
    for name, engine in [("saru", "voicevox"), ("miku", "openjtalk")]:
        character = config.load_character({**settings, "character": name})
        assert character.voice.engine == engine
        assert character.wake_words
        assert character.wake_reply == "はい"
    assert config.listen_mode(settings) == "wake"


def test_merge_is_deep_and_later_wins():
    assert config.merge({"a": {"x": 1, "y": 2}, "b": 1}, {"a": {"y": 3}}, None) == {"a": {"x": 1, "y": 3}, "b": 1}
