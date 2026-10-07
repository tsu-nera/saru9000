import os
import urllib.request

import pytest

import speech
from speech import Chunker, clean, duration, visemes, wav_duration


def chunk_stream(*deltas):
    chunker = Chunker()
    chunks = []
    for delta in deltas:
        chunks.extend(chunker.feed(delta))
    chunks.extend(chunker.flush())
    return chunks


def test_first_chunk_breaks_at_comma_and_later_ones_do_not():
    assert chunk_stream("うん、今日は晴れだね。散歩、行こうか。") == [
        "うん、",
        "今日は晴れだね。",
        "散歩、行こうか。",
    ]


def test_sentence_split_across_deltas_becomes_one_chunk():
    assert chunk_stream("こん", "にち", "は。元", "気？") == ["こんにちは。", "元気？"]


def test_chunk_ends_at_newline_and_exclamation():
    assert chunk_stream("やあ!\nまたね\nバイバイ！") == ["やあ!", "またね", "バイバイ！"]


def test_leftover_without_punctuation_is_flushed():
    chunker = Chunker()
    assert chunker.feed("そうだね。それで") == ["そうだね。"]
    assert chunker.flush() == ["それで"]
    assert chunker.flush() == []


def test_symbol_only_chunk_is_dropped_and_does_not_use_up_first():
    assert chunk_stream("😊\nええと、それは、") == ["ええと、", "それは、"]


def test_question_mark_inside_url_does_not_break():
    assert chunk_stream("見て https://example.com/a?b=1 これ。") == ["見て これ。"]


def test_clean_removes_symbols_emoji_and_urls():
    assert clean("**大事**なのは `code` だよ😊 https://example.com/x 。") == "大事なのは code だよ 。"
    assert clean("## 見出し\n- 項目") == "見出し 項目"
    assert clean("[リンク](https://example.com)を見て") == "リンクを見て"


def test_clean_keeps_numbers_and_prosody_marks():
    assert clean("気温は3.5度、湿度は80%！") == "気温は3.5度、湿度は80%！"


def test_clean_returns_empty_for_symbol_only_text():
    assert clean("😊✨") == ""
    assert clean("**---**") == ""
    assert clean("。！") == ""
    assert clean("https://example.com") == ""


def mora(consonant, vowel, c_frames, v_frames):
    """A mora whose lengths are exact frame multiples, so halving stays exact."""
    return {
        "consonant": consonant,
        "consonant_length": None if c_frames is None else c_frames / speech.FRAMES_PER_SECOND,
        "vowel": vowel,
        "vowel_length": v_frames / speech.FRAMES_PER_SECOND,
    }


def make_query(speed=1.0):
    return {
        "speedScale": speed,
        "prePhonemeLength": 8 / speech.FRAMES_PER_SECOND,
        "postPhonemeLength": 8 / speech.FRAMES_PER_SECOND,
        "accent_phrases": [
            {
                # ma(m closed + a) / ka(k + A devoiced -> a, merged with a) / N / cl
                "moras": [
                    mora("m", "a", 4, 8),
                    mora("k", "a", 6, 10),
                    mora("s", "I", 4, 8),
                    mora(None, "N", None, 6),
                    mora(None, "cl", None, 4),
                    mora("b", "o", 2, 12),
                ],
                "pause_mora": mora(None, "pau", None, 20),
            },
            {"moras": [mora("p", "u", 4, 8)], "pause_mora": None},
        ],
    }


def test_visemes_follow_the_rules():
    f = speech.FRAMES_PER_SECOND
    # frames: pre 0-8 | m 8-12 | a 12-20 | k+a 20-36 | s+I 36-48 | N 48-54
    # | cl 54-58 | b 58-60 | o 60-72 | pause 72-92 | p 92-96 | u 96-104 | post 104-112
    assert visemes(make_query()) == [
        {"t": 0 / f, "v": "closed"},
        {"t": 12 / f, "v": "a"},
        {"t": 36 / f, "v": "i"},
        {"t": 48 / f, "v": "closed"},
        {"t": 60 / f, "v": "o"},
        {"t": 72 / f, "v": "closed"},
        {"t": 96 / f, "v": "u"},
        {"t": 104 / f, "v": "closed"},
    ]


def test_duration_is_the_end_of_the_last_segment():
    assert duration(make_query()) == 112 / speech.FRAMES_PER_SECOND


def test_speed_scale_halves_the_times():
    normal = visemes(make_query(1.0))
    fast = visemes(make_query(2.0))
    assert [x["v"] for x in fast] == [x["v"] for x in normal]
    assert [x["t"] for x in fast] == [x["t"] / 2 for x in normal]
    assert duration(make_query(2.0)) == duration(make_query(1.0)) / 2


def test_zero_length_segments_are_dropped_before_merging():
    query = make_query()
    query["accent_phrases"][0]["moras"][1]["consonant_length"] = 0.0
    query["accent_phrases"][0]["moras"][0]["vowel_length"] = 0.0
    # m (closed) is now followed directly by "ka"'s vowel: the dropped 0-length
    # "a" does not split anything.
    assert [x["v"] for x in visemes(query)][:3] == ["closed", "a", "i"]


def test_pause_length_overrides_and_scales():
    query = make_query()
    query["pauseLength"] = 10 / speech.FRAMES_PER_SECOND
    query["pauseLengthScale"] = 2.0
    assert duration(query) == (112 - 20 + 20) / speech.FRAMES_PER_SECOND
    del query["pauseLength"]
    query["pauseLengthScale"] = 0.5
    assert duration(query) == (112 - 20 + 10) / speech.FRAMES_PER_SECOND


VOICEVOX_URL = os.environ.get("VOICEVOX_URL", speech.DEFAULT_URL)


def voicevox_reachable():
    try:
        urllib.request.urlopen(f"{VOICEVOX_URL.rstrip('/')}/version", timeout=1).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not voicevox_reachable(), reason="VOICEVOX is not reachable")
def test_duration_matches_the_real_wav():
    voicevox = speech.Voicevox(url=VOICEVOX_URL)
    result = voicevox._synthesize("今日はいい天気ですね。散歩に行こうかな。でも少し暑いかもしれません。")
    diff = abs(duration(result.query) - wav_duration(result.wav))
    print(f"duration diff: {diff * 1000:.2f} ms")
    assert diff <= 0.05
