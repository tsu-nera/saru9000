"""Read saru's replies aloud with VOICEVOX Engine or Open JTalk.

The reply streams in as text_delta fragments. Chunker cuts them into
speakable chunks and the character's engine synthesizes each chunk into a
wav and its visemes; the stage plays them. Synthesis runs faster than
playback (VOICEVOX RTF ~0.63 on vaio, Open JTalk ~0.1), so synthesizing the
next chunk while the current one plays keeps the voice from stalling. Only
the first chunk also breaks at "、": its synthesis time is the wait before
saru starts talking.
"""

import asyncio
import io
import json
import os
import re
import subprocess
import tempfile
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
# A chunk takes well under a second; a stuck open_jtalk is killed after this.
OPEN_JTALK_TIMEOUT = 30

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
    visemes: list  # [{"t": start seconds, "v": a/i/u/e/o/closed}] over the wav


def make_engine(settings, voice):
    """The engine voice (config.Voice) names, set up from the settings."""
    if voice.engine == "voicevox":
        return Voicevox(settings["voicevox_url"], voice)
    if voice.engine == "openjtalk":
        paths = settings["open_jtalk"]
        return OpenJTalk(os.path.expanduser(paths["bin"]), os.path.expanduser(paths["dic"]), voice)
    raise ValueError(f"unknown voice engine {voice.engine!r}")


class Voicevox:
    def __init__(self, url, voice):
        self.url = url.rstrip("/")
        self.voice = voice  # config.Voice
        self.name = f"VOICEVOX ({self.url})"

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
        query, wav = self._render(text)
        return Synthesis(wav=wav, visemes=visemes(query))

    def _render(self, text):
        """(audio_query, wav) for the text, the query tuned to the voice."""
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
        return query, wav

    async def synthesize(self, text):
        return await asyncio.to_thread(self._synthesize, text)


async def _run(args, text):
    """Run open_jtalk with text on stdin; OSError if it fails or hangs."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(OPEN_JTALK_TIMEOUT):
            _, stderr = await process.communicate(text.encode("utf-8"))
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        message = stderr.decode("utf-8", "replace").strip()
        raise OSError(f"open_jtalk exited with {process.returncode}: {message}")


class OpenJTalk:
    def __init__(self, bin, dic, voice, run=_run):
        self.bin = bin
        self.dic = dic
        self.voice = voice  # config.Voice
        self.run = run  # replaced by a fake in tests
        self.name = f"Open JTalk ({bin})"

    def args(self, wav_path, trace_path):
        return [
            self.bin,
            "-x", self.dic,
            "-m", self.voice.htsvoice,
            "-ow", str(wav_path),
            "-ot", str(trace_path),
            "-r", str(self.voice.speed),
            "-fm", str(self.voice.pitch),
            "-jf", str(self.voice.intonation),
        ]  # fmt: skip

    async def synthesize(self, text):
        trace, wav = await self._render(text)
        return Synthesis(wav=wav, visemes=label_visemes(trace))

    async def _render(self, text):
        """(trace, wav) open_jtalk writes for the text."""
        with tempfile.TemporaryDirectory(prefix="core-openjtalk-") as tmp:
            wav_path = os.path.join(tmp, "out.wav")
            trace_path = os.path.join(tmp, "trace.txt")
            await self.run(self.args(wav_path, trace_path), text)
            with open(wav_path, "rb") as f:
                wav = f.read()
            with open(trace_path, encoding="utf-8") as f:
                trace = f.read()
        return trace, wav


# VOICEVOX Engine renders 24000 Hz audio in hops of 256 samples.
FRAMES_PER_SECOND = 24000 / 256
VOWELS = set("aiueo")
CLOSED_CONSONANTS = {"m", "b", "p", "my", "by", "py"}


def _frames(seconds, speed):
    # Rounded per phoneme like the engine; summing seconds drifts from the wav's length.
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


def _merge(segments):
    """[{"t", "v"}] from (start, end, viseme): empty segments dropped, then repeats merged."""
    result = []
    for start, end, v in segments:
        if end == start:
            continue
        if result and result[-1]["v"] == v:
            continue
        result.append({"t": start, "v": v})
    return result


def visemes(query):
    """Mouth shapes over time from a VOICEVOX audio_query: [{"t": start seconds, "v": a/i/u/e/o/closed}]."""
    f = FRAMES_PER_SECOND
    return _merge((start / f, end / f, v) for start, end, v in _segments(query))


def duration(query):
    """Length in seconds of the audio the engine makes from the query."""
    return max((end for _, end, _ in _segments(query)), default=0) / FRAMES_PER_SECOND


def wav_duration(wav):
    with wave.open(io.BytesIO(wav)) as f:
        return f.getnframes() / f.getframerate()


# Open JTalk's trace (-ot) lists the phonemes it spoke under this heading, one
# "start end full-context-label" per line, times in units of 100 ns.
LABEL_HEADING = "[Output label]"
LABEL_UNIT = 10_000_000
# The phoneme is between "-" and "+" in "p1^p2-p3+p4=p5/A:...".
LABEL_PHONEME = re.compile(r"[^^]*\^[^-]*-([^+]*)\+")


def _labels(trace):
    """(start seconds, end seconds, phoneme) per line of the trace's [Output label] section."""
    lines = trace.split(LABEL_HEADING, 1)[1].splitlines()[1:]
    result = []
    for line in lines:
        if not line.strip():
            break
        start, end, label = line.split(maxsplit=2)
        phoneme = LABEL_PHONEME.match(label)
        if phoneme is None:
            raise ValueError(f"unexpected label in open_jtalk trace: {label!r}")
        result.append((int(start) / LABEL_UNIT, int(end) / LABEL_UNIT, phoneme.group(1)))
    return result


def label_visemes(trace):
    """Mouth shapes over time from an Open JTalk trace, by the same rules as visemes()."""
    labels = _labels(trace)
    # Walk backwards so a consonant can take the vowel that follows it.
    segments = []
    following = "closed"
    for start, end, phoneme in reversed(labels):
        if phoneme.lower() in VOWELS:
            v = phoneme.lower()
        elif phoneme in ("N", "cl", "pau", "sil") or phoneme in CLOSED_CONSONANTS:
            v = "closed"
        else:
            v = following
        following = v
        segments.append((start, end, v))
    return _merge(reversed(segments))


def label_duration(trace):
    """End in seconds of the last phoneme in an Open JTalk trace."""
    return max((end for _, end, _ in _labels(trace)), default=0)
