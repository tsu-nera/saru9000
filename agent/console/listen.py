#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["sherpa-onnx>=1.13.8", "numpy"]
# ///
"""Hear the user: microphone or wav files -> VAD -> ReazonSpeech k2-v2.

Silero VAD cuts the audio into utterances, each is recognized in-process with
sherpa-onnx. Models are downloaded to ~/.cache/saru9000/models on first use.

    ./listen.py              # microphone, one recognized sentence per line
    ./listen.py a.wav b.wav  # 16 kHz mono 16-bit wav files, no real-time wait
"""

import asyncio
import signal
import sys
import urllib.request
import wave
from pathlib import Path

SAMPLE_RATE = 16000
# Without silence around the segment ReazonSpeech drops the start of the
# sentence (measured on vaio: CER 0.10 -> 0.05 with 0.3s on both sides).
PAD_SECONDS = 0.3

VAD_THRESHOLD = 0.5
VAD_MIN_SPEECH = 0.25
# Silence that ends an utterance. Shorter splits one sentence at a breath or a
# "、" pause; longer adds directly to the wait before saru starts answering.
VAD_MIN_SILENCE = 0.6
# Silero's window size at 16 kHz.
VAD_WINDOW = 512
VAD_BUFFER_SECONDS = 60

# vaio has 2 cores: 4 threads measured slower than 2.
NUM_THREADS = 2

# Block size read from the microphone (0.1s).
BLOCK_SAMPLES = SAMPLE_RATE // 10

MODEL_DIR = Path.home() / ".cache" / "saru9000" / "models"
REAZON_DIR = MODEL_DIR / "reazonspeech-k2-v2"
REAZON_URL = "https://huggingface.co/reazon-research/reazonspeech-k2-v2/resolve/main/"
REAZON_FILES = (
    "encoder-epoch-99-avg-1.int8.onnx",
    "decoder-epoch-99-avg-1.int8.onnx",
    "joiner-epoch-99-avg-1.int8.onnx",
    "tokens.txt",
)
VAD_PATH = MODEL_DIR / "silero_vad.onnx"
VAD_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx"

# Bounds a stalled connection; the transfer itself may take minutes.
DOWNLOAD_TIMEOUT = 60


def download(url, path):
    """Fetch url to path via a .part file, so a cut-off download is never taken for a whole one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    print(f"downloading {path.name} ...", file=sys.stderr, flush=True)
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
        with part.open("wb") as f:
            while chunk := response.read(1 << 20):
                f.write(chunk)
    part.rename(path)


def ensure_models():
    wanted = [(REAZON_URL + name, REAZON_DIR / name) for name in REAZON_FILES]
    wanted.append((VAD_URL, VAD_PATH))
    for url, path in wanted:
        if not path.exists():
            download(url, path)


def load_vad():
    import sherpa_onnx

    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(VAD_PATH)
    config.silero_vad.threshold = VAD_THRESHOLD
    config.silero_vad.min_speech_duration = VAD_MIN_SPEECH
    config.silero_vad.min_silence_duration = VAD_MIN_SILENCE
    config.silero_vad.window_size = VAD_WINDOW
    config.sample_rate = SAMPLE_RATE
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=VAD_BUFFER_SECONDS)


def load_recognizer():
    """Return recognize(samples) -> str backed by ReazonSpeech k2-v2 (int8)."""
    import sherpa_onnx

    engine = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(REAZON_DIR / REAZON_FILES[0]),
        decoder=str(REAZON_DIR / REAZON_FILES[1]),
        joiner=str(REAZON_DIR / REAZON_FILES[2]),
        tokens=str(REAZON_DIR / REAZON_FILES[3]),
        num_threads=NUM_THREADS,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method="greedy_search",
    )

    def recognize(samples):
        stream = engine.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        engine.decode_stream(stream)
        return stream.result.text.strip()

    return recognize


def to_list(samples):
    """Plain list of floats; numpy blocks and lists both come in."""
    return samples.tolist() if hasattr(samples, "tolist") else list(samples)


class Listener:
    """Cut a sample stream into utterances and recognize them.

    Synchronous so that it can be tested with a fake VAD and recognizer and be
    run in a worker thread. While paused, samples are dropped before they reach
    the VAD, so saru's own voice and the audio heard while it thinks are never
    recognized.
    """

    def __init__(self, vad, recognize):
        self.vad = vad
        self.recognize = recognize
        self.paused = False
        self.pending = []
        # Bumped by pause() and resume(). pause() can arrive from the event
        # loop while feed() runs in a worker thread; a recognition that started
        # before it belongs to audio the caller has already given up on.
        self.generation = 0

    def feed(self, samples):
        """Add audio; return the texts of the utterances that finished."""
        if self.paused:
            return []
        self.pending.extend(to_list(samples))
        generation = self.generation
        end = len(self.pending) - len(self.pending) % VAD_WINDOW
        for start in range(0, end, VAD_WINDOW):
            self.vad.accept_waveform(self.pending[start : start + VAD_WINDOW])
        del self.pending[:end]
        return self.drain(generation)

    def flush(self):
        """Finish the stream (end of a wav): recognize what is still buffered."""
        if self.paused:
            return []
        generation = self.generation
        if self.pending:
            self.vad.accept_waveform(self.pending)
            self.pending = []
        self.vad.flush()
        return self.drain(generation)

    def drain(self, generation):
        texts = []
        pad = [0.0] * int(PAD_SECONDS * SAMPLE_RATE)
        while not self.vad.empty():
            segment = to_list(self.vad.front.samples)
            self.vad.pop()
            text = self.recognize(pad + segment + pad)
            if generation != self.generation:
                return []
            if text.strip():
                texts.append(text.strip())
        return texts

    def pause(self):
        self.paused = True
        self.generation += 1

    def resume(self):
        self.vad.reset()
        self.pending = []
        self.paused = False
        self.generation += 1


def open_listener():
    ensure_models()
    return Listener(load_vad(), load_recognizer())


async def microphone():
    """Yield 0.1s float32 blocks from the default source via pw-record."""
    import numpy as np

    process = await asyncio.create_subprocess_exec(
        "pw-record", "--rate", str(SAMPLE_RATE), "--channels", "1",
        "--format", "f32", "--raw", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        size = BLOCK_SAMPLES * 4
        while True:
            try:
                data = await process.stdout.readexactly(size)
            except asyncio.IncompleteReadError as e:
                # A partial tail (EOF mid-block) is dropped: pw-record died.
                code = await process.wait()
                raise RuntimeError(f"pw-record exited ({code}); is a microphone available?") from e
            yield np.frombuffer(data, dtype="<f4")
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()


async def wav_blocks(paths):
    """Yield float32 blocks from 16 kHz mono 16-bit wav files, without real-time pacing.

    A second of silence follows each file: the end of a file is the end of an
    utterance, and without it consecutive files would run into one sentence.
    """
    import numpy as np

    gap = np.zeros(SAMPLE_RATE, dtype=np.float32)
    for path in paths:
        try:
            w = wave.open(str(path), "rb")
        except (wave.Error, EOFError) as e:
            raise ValueError(f"{path}: not a readable wav ({e}); need 16 kHz mono 16-bit") from e
        with w:
            if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                raise ValueError(f"{path}: need 16 kHz mono 16-bit wav (16000 Hz, 1 ch, 16 bit)")
            while data := w.readframes(BLOCK_SAMPLES):
                yield np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
        yield gap


async def utterances(listener, blocks):
    """Pull-based: recognized texts from blocks. Nothing is read while the consumer is busy."""
    async for block in blocks:
        for text in await asyncio.to_thread(listener.feed, block):
            yield text
    for text in await asyncio.to_thread(listener.flush):
        yield text


async def pump(listener, blocks, queue):
    """Push-based: keep reading blocks while the consumer is busy, and queue the texts.

    A paused Listener drops the audio, so the pipe never fills with stale sound.
    """
    async for text in utterances(listener, blocks):
        await queue.put(text)


async def run_cli(paths):
    listener = open_listener()
    blocks = wav_blocks(paths) if paths else microphone()
    async for text in utterances(listener, blocks):
        print(text, flush=True)


def raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def main():
    # Same approach as chat.py: a plain KeyboardInterrupt unwinds through the
    # async generators, whose finally kills pw-record.
    signal.signal(signal.SIGINT, raise_keyboard_interrupt)
    try:
        asyncio.run(run_cli(sys.argv[1:]))
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError) as e:
        sys.exit(f"listen.py: {e}")


if __name__ == "__main__":
    main()
