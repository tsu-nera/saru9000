from speech import Chunker, clean


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
