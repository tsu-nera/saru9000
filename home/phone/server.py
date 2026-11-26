import io
import json
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RATE = 8000
MAX_WAV_SECONDS = 180
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# 時刻・IP・"audio=64000/0" の統計行を拾わないよう、コードの後ろに説明文が続く形だけを見る
DECLINED = re.compile(r"(?<![\d.])(603|486)\s+[A-Za-z]")
GAVE_UP = re.compile(r"(?<![\d.])(408|480)\s+[A-Za-z]")
STATUS = re.compile(
    r"SIP Progress|(?<![\d.])[1-6]\d\d\s+[A-Za-z]|session closed|terminated|Function not implemented"
)
DURATION = re.compile(r"duration: (\d+) secs")

_lock = threading.Lock()


def clean(line: str) -> str:
    return ANSI.sub("", line).replace("\r", "").strip()


def classify(lines: list[str], ring_timed_out: bool) -> dict:
    lines = [x for x in (clean(x) for x in lines) if x]
    duration = 0
    for x in lines:
        m = DURATION.search(x)
        if m:
            duration = int(m.group(1))
    detail = next((x for x in reversed(lines) if STATUS.search(x)), lines[-1] if lines else "")
    if any("Call established" in x for x in lines):
        result = "answered"
    elif any(DECLINED.search(x) for x in lines):
        result = "declined"
    elif ring_timed_out:
        result = "no_answer"
    elif any(GAVE_UP.search(x) for x in lines):
        result = "no_answer"
    else:
        result = "failed"
    return {
        "result": result,
        "duration": duration if result == "answered" else 0,
        "detail": detail[:200],
    }


def synthesize(text: str, voicevox: str, speaker: int) -> bytes:
    """8 kHz・モノラル・16 bit の PCM フレームを返す（VOICEVOX 側でその形式で出させる）"""
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{voicevox}/audio_query?{q}", method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        query = json.load(r)
    query["outputSamplingRate"] = RATE
    query["outputStereo"] = False
    req = urllib.request.Request(
        f"{voicevox}/synthesis?speaker={speaker}",
        data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    with wave.open(io.BytesIO(data)) as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, RATE):
            raise RuntimeError(f"unexpected wav params: {w.getparams()}")
        return w.readframes(w.getnframes())


def repeat_frames(frames: bytes, repeat: int) -> bytes:
    silence = b"\x00\x00" * RATE
    return silence.join([frames] * repeat)


def write_wav(path: Path, body: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(body)


def lan_ipv4() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("1.1.1.1", 53))  # UDP の connect はパケットを出さない
        return s.getsockname()[0]


def run_baresip(tmp: Path, target: str, wav_seconds: float, ring_timeout: int) -> tuple[list[str], bool]:
    hard_limit = int(ring_timeout + wav_seconds + 30)
    proc = subprocess.Popen(
        ["baresip", "-f", str(tmp), "-e", f"/dial {target}", "-t", str(hard_limit)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
    )
    q: queue.Queue = queue.Queue()

    def reader():
        for line in proc.stdout:
            q.put(line)
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    lines: list[str] = []
    started = time.monotonic()
    hangup_at = None
    sigint_at = None
    ring_timed_out = False
    eof = False
    while not eof:
        try:
            line = q.get(timeout=0.2)
        except queue.Empty:
            line = ""
        if line is None:
            eof = True
        elif line:
            lines.append(line)
            if hangup_at is None and "Call established" in line:
                hangup_at = time.monotonic() + wav_seconds + 1
        now = time.monotonic()
        if sigint_at is None:
            if hangup_at is None and now - started > ring_timeout:
                ring_timed_out = True
                proc.send_signal(signal.SIGINT)
                sigint_at = now
            elif hangup_at is not None and now > hangup_at:
                proc.send_signal(signal.SIGINT)
                sigint_at = now
        elif now - sigint_at > 5:
            proc.kill()
    proc.wait()
    return lines, ring_timed_out


def do_call(text: str, repeat: int) -> tuple[int, dict]:
    if not _lock.acquire(blocking=False):
        return 409, {"result": "busy", "duration": 0, "detail": "another call in progress"}
    tmp = Path(tempfile.mkdtemp(prefix="phone-"))
    try:
        frames = synthesize(
            text,
            os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021"),
            int(os.environ.get("PHONE_SPEAKER", "3")),
        )
        body = repeat_frames(frames, repeat)
        wav_seconds = len(body) / 2 / RATE
        if wav_seconds > MAX_WAV_SECONDS:
            return 400, {"result": "failed", "duration": 0, "detail": f"too long: {wav_seconds:.0f}s"}
        write_wav(tmp / "speech.wav", body)
        target = os.environ["PHONE_SIP_TARGET"]
        if "transport=" not in target:
            # 付けないと出た瞬間に Function not implemented [38] で切れる
            target += ";transport=udp"
        shutil.copy(Path(__file__).parent / "baresip" / "config", tmp / "config")
        with open(tmp / "config", "a") as f:
            f.write(f"audio_source\t\taufile,{tmp / 'speech.wav'}\n")
            f.write(f"audio_player\t\taufile,{tmp / 'heard.wav'}\n")
            f.write(f"audio_alert\t\taufile,{tmp / 'alert.wav'}\n")
        (tmp / "accounts").write_text(
            f"<sip:saru9000@{lan_ipv4()}>;regint=0;audio_codecs=PCMU,PCMA;mediaenc=srtp-mand\n"
        )
        (tmp / "contacts").write_text("")
        lines, timed_out = run_baresip(
            tmp, target, wav_seconds, int(os.environ.get("PHONE_RING_TIMEOUT", "45"))
        )
        return 200, classify(lines, timed_out)
    except Exception as e:
        print(f"call failed: {e!r}", file=sys.stderr)
        return 200, {"result": "failed", "duration": 0, "detail": repr(e)[:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _lock.release()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/call":
            return self._send(404, {"result": "failed", "duration": 0, "detail": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            text = req["text"]
            repeat = req.get("repeat", 3)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text is empty")
            if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 10:
                raise ValueError("repeat must be 1..10")
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, {"result": "failed", "duration": 0, "detail": f"bad request: {e}"})
        self._send(*do_call(text.strip(), repeat))

    def log_message(self, fmt, *args):
        print(fmt % args, file=sys.stderr)


def main():
    os.environ["PHONE_SIP_TARGET"]  # 未設定なら KeyError で起動しない
    port = int(os.environ.get("PHONE_HTTP_PORT", "8590"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
