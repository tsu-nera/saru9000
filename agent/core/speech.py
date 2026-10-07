"""Read saru's replies aloud with VOICEVOX Engine.

The reply streams in as text_delta fragments. Chunker cuts them into
speakable chunks and VOICEVOX synthesizes each chunk; the stage plays them.
Synthesis runs faster than playback (RTF ~0.63 on vaio), so synthesizing the
next chunk while the current one plays keeps the voice from stalling. Only
the first chunk also breaks at "、": its synthesis time is the wait before
saru starts talking.
"""

import asyncio
import io
import json
import re
import unicodedata
import urllib.parse
import urllib.request
import wave
from dataclasses import dataclass

# Silence VOICEVOX puts before and after every chunk (its default is 0.1s
# each), which opened a gap between chunks of one reply.
EDGE_SILENCE = 0.05

BREAKS = set("。！？!?\n")
FIRST_BREAKS = BREAKS | {"、"}

# Bounds how long a Ctrl-C waits for an in-flight synthesis thread.
HTTP_TIMEOUT = 30

MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
URL = re.compile(r"https?://[\x21-\x7e]+")
OPEN_URL = re.compile(r"https?://[\x21-\x7e]*$")
# Symbols VOICEVOX reads or uses for intonation; every other symbol goes.
KEPT_SYMBOLS = set("、。，．！？!?,.%％")


def clean(text):
    """Strip what should not be read aloud; "" if nothing speakable is left."""
    text = MARKDOWN_LINK.sub(r"\1", text)
    text = URL.sub(" ", text)
    text = "".join(
        ch
        for ch in text
        if ch.isspace() or unicodedata.category(ch)[0] in "LN" or ch in KEPT_SYMBOLS
    )
    text = re.sub(r"\s+", " ", text).strip()
    if not any(unicodedata.category(ch)[0] in "LN" for ch in text):
        return ""
    return text


class Chunker:
    """Cut streamed text into cleaned chunks to synthesize one by one."""

    def __init__(self):
        self.buffer = ""
        self.first = True

    def feed(self, text):
        chunks = []
        for ch in text:
            self.buffer += ch
            breaks = FIRST_BREAKS if self.first else BREAKS
            # "?" inside a URL is not the end of a sentence.
            if ch in breaks and not OPEN_URL.search(self.buffer[:-1]):
                chunks.extend(self._emit())
        return chunks

    def flush(self):
        return self._emit()

    def _emit(self):
        text = clean(self.buffer)
        self.buffer = ""
        if not text:
            return []
        self.first = False
        return [text]


@dataclass
class Synthesis:
    wav: bytes
    # The audio_query the wav was made from; visemes() derives lip sync from it.
    query: dict


class Voicevox:
    def __init__(self, url, voice):
        self.url = url.rstrip("/")
        self.voice = voice  # config.Voice

    def _post(self, path, params, body=b""):
        request = urllib.request.Request(
            f"{self.url}{path}?{urllib.parse.urlencode(params)}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
            return response.read()

    def _synthesize(self, text):
        speaker = self.voice.speaker
        query = json.loads(self._post("/audio_query", {"text": text, "speaker": speaker}))
        query["speedScale"] = self.voice.speed
        query["pitchScale"] = self.voice.pitch
        query["intonationScale"] = self.voice.intonation
        query["prePhonemeLength"] = EDGE_SILENCE
        query["postPhonemeLength"] = EDGE_SILENCE
        wav = self._post(
            "/synthesis",
            {"speaker": speaker},
            json.dumps(query).encode("utf-8"),
        )
        return Synthesis(wav=wav, query=query)

    async def synthesize(self, text):
        return await asyncio.to_thread(self._synthesize, text)


# VOICEVOX Engine renders 24000 Hz audio in hops of 256 samples.
FRAMES_PER_SECOND = 24000 / 256
VOWELS = set("aiueo")
CLOSED_CONSONANTS = {"m", "b", "p", "my", "by", "py"}


def _frames(seconds, speed):
    # Python's round() and numpy's both round half to even, like the engine.
    return round(seconds / speed * FRAMES_PER_SECOND)


def _segments(query):
    """Yield (start_frame, end_frame, viseme) per phoneme, the way the engine lays them out.

    The engine rounds every phoneme to whole frames on its own, so the total
    only matches the wav length if this does the same; summing seconds first
    would let the error build up.
    """
    speed = query["speedScale"]
    pos = 0

    def segment(seconds, v):
        nonlocal pos
        start = pos
        pos += _frames(seconds, speed)
        return start, pos, v

    yield segment(query["prePhonemeLength"], "closed")
    for phrase in query["accent_phrases"]:
        for mora in phrase["moras"]:
            vowel = mora["vowel"]
            v = vowel.lower() if vowel.lower() in VOWELS else "closed"
            if mora["consonant_length"] is not None:
                closed = mora["consonant"] in CLOSED_CONSONANTS
                yield segment(mora["consonant_length"], "closed" if closed else v)
            yield segment(mora["vowel_length"], v)
        pause = phrase.get("pause_mora")
        if pause is not None:
            length = query.get("pauseLength")
            if length is None:
                length = pause["vowel_length"]
            yield segment(length * query.get("pauseLengthScale", 1.0), "closed")
    yield segment(query["postPhonemeLength"], "closed")


def visemes(query):
    """Mouth shapes over time: [{"t": start seconds, "v": a/i/u/e/o/closed}]."""
    result = []
    for start, end, v in _segments(query):
        if end == start:
            continue
        if result and result[-1]["v"] == v:
            continue
        result.append({"t": start / FRAMES_PER_SECOND, "v": v})
    return result


def duration(query):
    """Length in seconds of the audio the engine makes from the query."""
    return max((end for _, end, _ in _segments(query)), default=0) / FRAMES_PER_SECOND


def wav_duration(wav):
    with wave.open(io.BytesIO(wav)) as f:
        return f.getnframes() / f.getframerate()
