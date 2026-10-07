"""Read saru's replies aloud with VOICEVOX Engine.

The reply streams in as text_delta fragments. Chunker cuts them into
speakable chunks, VOICEVOX synthesizes each chunk and pw-play plays it.
Synthesis runs faster than playback (RTF ~0.63 on vaio), so synthesizing the
next chunk while the current one plays keeps the voice from stalling. Only
the first chunk also breaks at "、": its synthesis time is the wait before
saru starts talking.
"""

import asyncio
import json
import re
import tempfile
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "http://127.0.0.1:50021"
DEFAULT_SPEAKER = 3
# VOICEVOX's 1.0 felt slow in conversation. Faster speech also synthesizes
# faster, but short chunks then run close to RTF 1 on vaio.
DEFAULT_SPEED = 1.2
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
    # Kept for lip sync in the browser later; playback only uses the wav.
    query: dict


class Voicevox:
    def __init__(self, url=DEFAULT_URL, speaker=DEFAULT_SPEAKER, speed=DEFAULT_SPEED):
        self.url = url.rstrip("/")
        self.speaker = speaker
        self.speed = speed

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
        query = json.loads(self._post("/audio_query", {"text": text, "speaker": self.speaker}))
        query["speedScale"] = self.speed
        query["prePhonemeLength"] = EDGE_SILENCE
        query["postPhonemeLength"] = EDGE_SILENCE
        wav = self._post(
            "/synthesis",
            {"speaker": self.speaker},
            json.dumps(query).encode("utf-8"),
        )
        return Synthesis(wav=wav, query=query)

    async def synthesize(self, text):
        return await asyncio.to_thread(self._synthesize, text)


class PlaybackError(Exception):
    pass


async def play(wav):
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        f.write(wav)
        f.flush()
        process = await asyncio.create_subprocess_exec(
            "pw-play",
            f.name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await process.communicate()
        except asyncio.CancelledError:
            # Ctrl-C cancels this task: stop the sound instead of leaving it on.
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or f"exit {process.returncode}"
        raise PlaybackError(f"pw-play: {message}")


class SpeechPipeline:
    """Synthesize and play one reply, two queues deep so both run at once.

    On the first failure the rest of the reply is dropped and the error is
    returned from finish(); the text chat goes on either way.
    """

    def __init__(self, voicevox):
        self.voicevox = voicevox
        self.chunker = Chunker()
        self.texts = asyncio.Queue()
        self.sounds = asyncio.Queue()
        self.error = None
        self.tasks = [
            asyncio.create_task(self._synthesize_all()),
            asyncio.create_task(self._play_all()),
        ]

    def feed(self, delta):
        for chunk in self.chunker.feed(delta):
            self.texts.put_nowait(chunk)

    async def finish(self):
        """Wait until the whole reply has been played; return the error if any."""
        for chunk in self.chunker.flush():
            self.texts.put_nowait(chunk)
        self.texts.put_nowait(None)
        await asyncio.gather(*self.tasks)
        return self.error

    def cancel(self):
        for task in self.tasks:
            task.cancel()

    async def _synthesize_all(self):
        while (text := await self.texts.get()) is not None:
            if self.error:
                continue
            try:
                sound = await self.voicevox.synthesize(text)
            except (OSError, ValueError) as e:
                self.error = f"VOICEVOX ({self.voicevox.url}): {e}"
                continue
            self.sounds.put_nowait(sound)
        self.sounds.put_nowait(None)

    async def _play_all(self):
        while (sound := await self.sounds.get()) is not None:
            if self.error:
                continue
            try:
                await play(sound.wav)
            except (OSError, PlaybackError) as e:
                self.error = str(e)
