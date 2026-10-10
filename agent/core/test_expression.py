import expression
from expression import Extractor, Tag


def run(*fragments):
    extractor = Extractor()
    parts = []
    for fragment in fragments:
        parts.extend(extractor.feed(fragment))
    parts.extend(extractor.flush())
    text = "".join(p for p in parts if isinstance(p, str))
    return text, [p.name for p in parts if isinstance(p, Tag)]


def test_tag_is_removed_and_named():
    assert run("[happy]こんにちは") == ("こんにちは", ["happy"])


def test_tag_split_across_fragments():
    assert run("[hap", "py]こんにちは") == ("こんにちは", ["happy"])
    assert run("[", "s", "urprised", "]", "えっ") == ("えっ", ["surprised"])


def test_parts_keep_their_order():
    extractor = Extractor()
    parts = extractor.feed("うん。[sad]ざん") + extractor.feed("ねん")
    assert parts == ["うん。", Tag("sad"), "ざん", "ねん"]


def test_unknown_name_is_text():
    assert run("[unknown]だよ") == ("[unknown]だよ", [])


def test_long_brackets_are_text():
    # 13 characters with both brackets: one past the limit.
    long = "[abcdefghijk]"
    assert len(long) == 13
    assert run(long + "だよ") == (long + "だよ", [])
    assert run("[abcde", "fghijk]だよ") == (long + "だよ", [])


def test_non_tag_brackets_pass_through():
    assert run("[リンク](https://example.com)") == ("[リンク](https://example.com)", [])
    assert run("[Happy]") == ("[Happy]", [])
    # A "[" that turns out not to be a tag may open one right after.
    assert run("[[angry]むっ") == ("[むっ", ["angry"])


def test_unclosed_tag_is_flushed_as_text():
    assert run("おわり[hap") == ("おわり[hap", [])


def test_brain_note_lists_every_tag():
    note = expression.brain_note()
    assert all(f"[{name}]" in note for name in expression.NAMES)
    assert f"{len(expression.NAMES)}つだけ" in note
