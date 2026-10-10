"""Dances asked for with fixed words; the brain is never asked.

config.json "dances" lists the songs. A song's phrase (「ミクミクにして」)
starts it at once; a menu phrase (「踊って」「何が踊れる？」) lists the songs
and the next sentence picks one by a choice word (「テルユア」「2番」).
Stdlib only, like session.py.
"""

import unicodedata
from dataclasses import dataclass


def normalize(text):
    """For matching: width and case folded, hiragana as katakana, only letters and digits kept."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in text)
    return "".join(c for c in text if c.isalnum())


def _contains(text, words):
    return _longest(text, words) > 0


def _longest(text, words):
    """Length of the longest word text contains, 0 for none."""
    heard = normalize(text)
    return max((len(w) for w in map(normalize, words) if w and w in heard), default=0)


def _best(songs, text, words_of):
    """The song with the longest word in text, so 「テルユアワールド完全版」 beats 「テルユアワールド」."""
    length, song = max(((_longest(text, words_of(s)), s) for s in songs), key=lambda p: p[0], default=(0, None))
    return song if length else None


@dataclass(frozen=True)
class Dance:
    motion: str  # the stage's motion name
    name: str  # read out in the menu
    phrases: tuple[str, ...]  # start it at once
    choices: tuple[str, ...]  # pick it after the menu
    cue: str  # said right before it starts


class Dances:
    def __init__(self, songs=(), menu_phrases=(), cancel=""):
        self.songs = tuple(songs)
        self.menu_phrases = tuple(menu_phrases)
        self.cancel = cancel  # said when the sentence after the menu picks nothing

    @classmethod
    def from_config(cls, config):
        cue = config.get("cue", "")
        menu = config.get("menu", {})
        songs = [
            Dance(
                motion=song["motion"],
                name=song["name"],
                phrases=tuple(song.get("phrases", ())),
                choices=tuple(song.get("choices", ())),
                cue=song.get("cue", cue),
            )
            for song in config.get("songs", ())
        ]
        return cls(songs, menu.get("phrases", ()), menu.get("cancel", ""))

    def requested(self, text):
        """The song whose phrase text contains, or None."""
        return _best(self.songs, text, lambda song: song.phrases)

    def asks_menu(self, text):
        return bool(self.songs) and _contains(text, self.menu_phrases)

    def menu(self):
        names = "と、".join(song.name for song in self.songs)
        return f"{names}が踊れるよ。どれにする？"

    def chosen(self, text):
        """The song the sentence after the menu picks (a phrase, choice word or name), or None."""
        return _best(self.songs, text, lambda song: song.phrases + song.choices + (song.name,))

    def brain_note(self):
        """A line for the system prompt, so the brain names only real songs."""
        if not self.songs:
            return ""
        names = "、".join(f"「{song.name}」" for song in self.songs)
        return (
            f"## 踊り\n\nあなたが踊れる曲は{names}だけです。踊りはあなたの返事とは別に始まるので、"
            "踊りたいと言われたら「踊って」と声をかければ曲を選べると伝えます。"
        )
