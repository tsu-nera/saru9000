"""Pull expression tags like "[happy]" out of the streamed reply.

The brain writes a tag at the start of a sentence instead of calling a tool,
so the stage can change the face without an extra round trip. A tag may be
split across text_delta fragments, so "[" up to "]" is held back, but at most
MAX_TAG characters: anything longer, or with a character other than a-z, is
not a tag and goes on as text (speech.clean() strips the brackets later).
"""

from dataclasses import dataclass

NAMES = ("happy", "sad", "angry", "surprised", "relaxed", "neutral")
# Longest held "[...]" including both brackets.
MAX_TAG = 12


def brain_note():
    """The system prompt's part on tags, built from NAMES so the two never drift."""
    tags = " ".join(f"[{name}]" for name in NAMES)
    return (
        "## 表情\n\n"
        "表情を変えたいときは、文の頭に表情タグを付けられます。タグは読み上げられず、顔の表情になります。\n\n"
        f"- 使えるタグは {tags} の{len(NAMES)}つだけ\n"
        "- 半角の角括弧と英小文字でそのまま書く。例: [happy]やったね、うれしい。\n"
        "- 付けるのは文の頭に1つまで。毎文付けなくてよく、気持ちが変わったときだけ付ける"
    )


@dataclass(frozen=True)
class Tag:
    name: str


class Extractor:
    """Split streamed text into str parts and Tag parts, in order."""

    def __init__(self):
        self.held = ""

    def feed(self, text):
        parts = []
        for ch in text:
            self._push(ch, parts)
        return parts

    def flush(self):
        parts = []
        self._text(self.held, parts)
        self.held = ""
        return parts

    def _push(self, ch, parts):
        if not self.held:
            if ch == "[":
                self.held = ch
            else:
                self._text(ch, parts)
            return
        if ch == "]":
            name = self.held[1:]
            if name in NAMES:
                parts.append(Tag(name))
            else:
                self._text(self.held + ch, parts)
            self.held = ""
        elif "a" <= ch <= "z" and len(self.held) < MAX_TAG - 1:
            self.held += ch
        else:
            # Not a tag. ch itself may open the next one.
            self._text(self.held, parts)
            self.held = ""
            self._push(ch, parts)

    @staticmethod
    def _text(text, parts):
        if not text:
            return
        if parts and isinstance(parts[-1], str):
            parts[-1] += text
        else:
            parts.append(text)

