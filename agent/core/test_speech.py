import asyncio
import os
import urllib.request

import pytest

import config
import speech
from speech import Chunker, clean, duration, label_duration, label_visemes, visemes, wav_duration


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


VOICEVOX_URL = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")


def voicevox_reachable():
    try:
        urllib.request.urlopen(f"{VOICEVOX_URL.rstrip('/')}/version", timeout=1).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not voicevox_reachable(), reason="VOICEVOX is not reachable")
def test_duration_matches_the_real_wav():
    voice = config.Voice(engine="voicevox", speaker=3, speed=1.2, pitch=0.0, intonation=1.0)
    voicevox = speech.Voicevox(VOICEVOX_URL, voice)
    query, wav = voicevox._render("今日はいい天気ですね。散歩に行こうかな。でも少し暑いかもしれません。")
    diff = abs(duration(query) - wav_duration(wav))
    print(f"duration diff: {diff * 1000:.2f} ms")
    assert diff <= 0.05


# Trimmed from open_jtalk -ot traces of "さんぽ、ですか。" and "まぶしい、きっとね。"
# (TYPE-β, -r 1.0); the full-context labels are cut after "/A:".
TRACE_HEAD = """[Text analysis result]
さんぽ,名詞,一般,*,*,*,*,散歩,サンポ,サンポ,0/3,C2,-1

[Output label]
"""
TRACE_TAIL = """
[Global parameter]
Sampring frequency                     ->    48000(Hz)
"""
SANPO = (
    TRACE_HEAD
    + """0 250000 xx^xx-sil+s=a/A:xx+xx+xx
250000 1200000 xx^sil-s+a=N/A:0+1+3
1200000 2350000 sil^s-a+N=p/A:0+1+3
2350000 3250000 s^a-N+p=o/A:1+2+2
3250000 3850000 a^N-p+o=pau/A:2+3+1
3850000 5100000 N^p-o+pau=d/A:2+3+1
5100000 7200000 p^o-pau+d=e/A:xx+xx+xx
7200000 7750000 o^pau-d+e=s/A:0+1+3
7750000 8250000 pau^d-e+s=U/A:0+1+3
8250000 8950000 d^e-s+U=k/A:1+2+2
8950000 9800000 e^s-U+k=a/A:1+2+2
9800000 10400000 s^U-k+a=sil/A:2+3+1
10400000 11400000 U^k-a+sil=xx/A:2+3+1
11400000 11650000 k^a-sil+xx=xx/A:xx+xx+xx
"""
    + TRACE_TAIL
)
MABUSHII = (
    TRACE_HEAD
    + """0 250000 xx^xx-sil+m=a/A:xx+xx+xx
250000 700000 xx^sil-m+a=b/A:-2+1+4
700000 1500000 sil^m-a+b=u/A:-2+1+4
1500000 2100000 m^a-b+u=sh/A:-1+2+3
2100000 2650000 a^b-u+sh=i/A:-1+2+3
2650000 3450000 b^u-sh+i=i/A:0+3+2
3450000 4450000 u^sh-i+i=pau/A:0+3+2
4450000 5750000 sh^i-i+pau=k/A:1+4+1
5750000 7300000 i^i-pau+k=i/A:xx+xx+xx
7300000 7850000 i^pau-k+i=cl/A:-2+1+4
7850000 8850000 pau^k-i+cl=t/A:-2+1+4
8850000 9250000 k^i-cl+t=o/A:-1+2+3
9250000 9650000 i^cl-t+o=n/A:0+3+2
9650000 10550000 cl^t-o+n=e/A:0+3+2
10550000 10900000 t^o-n+e=sil/A:1+4+1
10900000 12000000 o^n-e+sil=xx/A:1+4+1
12000000 12250000 n^e-sil+xx=xx/A:xx+xx+xx
"""
    + TRACE_TAIL
)


def test_label_visemes_follow_the_rules():
    # s->a, N and p closed, pau closed, d->e, s->devoiced U->u, k->a, sil closed
    assert label_visemes(SANPO) == [
        {"t": 0.0, "v": "closed"},
        {"t": 0.025, "v": "a"},
        {"t": 0.235, "v": "closed"},
        {"t": 0.385, "v": "o"},
        {"t": 0.51, "v": "closed"},
        {"t": 0.72, "v": "e"},
        {"t": 0.825, "v": "u"},
        {"t": 0.98, "v": "a"},
        {"t": 1.14, "v": "closed"},
    ]
    # sil+m and b closed, sh/k/t/n take their vowel, i+i merged, cl closed
    assert label_visemes(MABUSHII) == [
        {"t": 0.0, "v": "closed"},
        {"t": 0.07, "v": "a"},
        {"t": 0.15, "v": "closed"},
        {"t": 0.21, "v": "u"},
        {"t": 0.265, "v": "i"},
        {"t": 0.575, "v": "closed"},
        {"t": 0.73, "v": "i"},
        {"t": 0.885, "v": "closed"},
        {"t": 0.925, "v": "o"},
        {"t": 1.055, "v": "e"},
        {"t": 1.2, "v": "closed"},
    ]


def test_label_duration_is_the_end_of_the_last_label():
    assert label_duration(SANPO) == 1.165
    assert label_duration(MABUSHII) == 1.225


def test_zero_length_labels_are_dropped_before_merging():
    # The "o" of "ぽ" shrinks to nothing: N, p and pau become one closed stretch.
    trace = SANPO.replace("3850000 5100000 N^p-o", "3850000 3850000 N^p-o").replace(
        "5100000 7200000 p^o-pau", "3850000 7200000 p^o-pau"
    )
    assert [x["v"] for x in label_visemes(trace)][:4] == ["closed", "a", "closed", "e"]


def openjtalk_voice(**overrides):
    voice = {"htsvoice": "/voices/x.htsvoice", "speed": 1.2, "pitch": 2.0, "intonation": 1.5}
    return config.Voice(engine="openjtalk", **{**voice, **overrides})


def options(args):
    return dict(zip(args[1::2], args[2::2]))


def test_make_engine_builds_openjtalk_from_the_character_voice():
    settings = {"voicevox_url": "http://x", "open_jtalk": {"bin": "~/oj/open_jtalk", "dic": "/oj/dic"}}
    engine = speech.make_engine(settings, openjtalk_voice())
    assert isinstance(engine, speech.OpenJTalk)
    calls = []

    async def fake_run(args, text):
        calls.append((args, text))
        with open(options(args)["-ow"], "wb") as f:
            f.write(b"RIFF fake")
        with open(options(args)["-ot"], "w", encoding="utf-8") as f:
            f.write(SANPO)

    engine.run = fake_run
    result = asyncio.run(engine.synthesize("さんぽ、ですか。"))
    assert result.wav == b"RIFF fake"
    assert result.visemes == label_visemes(SANPO)
    [(args, text)] = calls
    assert text == "さんぽ、ですか。"
    assert args[0] == os.path.expanduser("~/oj/open_jtalk")
    opt = options(args)
    assert opt["-x"] == "/oj/dic"
    assert opt["-m"] == "/voices/x.htsvoice"
    assert (opt["-r"], opt["-fm"], opt["-jf"]) == ("1.2", "2.0", "1.5")


def test_make_engine_builds_voicevox_from_the_character_voice():
    voice = config.Voice(engine="voicevox", speaker=3, speed=1.2, pitch=0.0, intonation=1.0)
    engine = speech.make_engine({"voicevox_url": "http://127.0.0.1:50021/"}, voice)
    assert isinstance(engine, speech.Voicevox)
    assert engine.url == "http://127.0.0.1:50021"


def test_openjtalk_failure_is_an_oserror(tmp_path):
    missing = speech.OpenJTalk(str(tmp_path / "open_jtalk"), "/dic", openjtalk_voice())
    with pytest.raises(OSError):
        asyncio.run(missing.synthesize("あ。"))
    failing = speech.OpenJTalk("false", "/dic", openjtalk_voice())
    with pytest.raises(OSError, match="exited with 1"):
        asyncio.run(failing.synthesize("あ。"))


OPEN_JTALK = os.path.expanduser("~/.local/opt/open_jtalk/bin/open_jtalk")
OPEN_JTALK_DIC = os.path.expanduser("~/.local/opt/open_jtalk/open_jtalk_dic_utf_8-1.11")
TYPE_B = os.path.expanduser("~/.cache/saru9000/voices/naip_type_b.htsvoice")


@pytest.mark.skipif(
    not all(os.path.exists(p) for p in (OPEN_JTALK, OPEN_JTALK_DIC, TYPE_B)),
    reason="open_jtalk, its dictionary or naip_type_b.htsvoice is missing",
)
@pytest.mark.parametrize("speed", [1.0, 1.2])
def test_label_duration_matches_the_real_wav(speed):
    voice = openjtalk_voice(htsvoice=TYPE_B, speed=speed, pitch=0.0, intonation=1.0)
    engine = speech.OpenJTalk(OPEN_JTALK, OPEN_JTALK_DIC, voice)
    trace, wav = asyncio.run(engine._render("今日はいい天気ですね。散歩に行こうかな。でも少し暑いかもしれません。"))
    end = label_duration(trace)
    assert label_visemes(trace)[-1]["t"] < end
    diff = abs(end - wav_duration(wav))
    print(f"speed {speed}: label end {end:.3f}s, wav {wav_duration(wav):.3f}s, diff {diff * 1000:.2f} ms")
    assert diff <= 0.05
