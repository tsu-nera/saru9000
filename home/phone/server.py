import io
import json
import os
import queue
import re
import shutil
import string
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
HOME = Path(os.environ.get("PHONE_HOME", "/var/lib/phone"))
# 標準入力が端末でないので、プロンプト "linphonec> " が次の出力の行頭にくっつく
CONNECTED = re.compile(r"Call \d+ with \S+ connected\.")
ENDED = re.compile(r"Call \d+ with \S+ ended \((.*)\)\.")
# 呼び出し中に断られたものは理由を出さず error. だけになる（話し中 486・相手側の時間切れ 408/480 もここ）
ERROR = re.compile(r"Call \d+ with \S+ error\.")
# 603 だけは liblinphone が error でなく ended にする（理由は linphone_reason_to_string の文字列）
DECLINED_REASONS = {"Call declined"}
REGISTERED = re.compile(r"registered, identity=")
NOT_REGISTERED = re.compile(r"registered=-?\d")

_lock = threading.Lock()


def classify(events: list[tuple[float, str]], ring_timed_out: bool) -> dict:
    """events は (受け取った時刻, linphonec の出力の行)"""
    events = [(t, x.replace("\r", "").strip()) for t, x in events]
    events = [(t, x) for t, x in events if x]
    connected_at = next((t for t, x in events if CONNECTED.search(x)), None)
    end = next(((t, x) for t, x in events if ENDED.search(x) or ERROR.search(x)), None)
    detail = end[1] if end else (events[-1][1] if events else "")
    if connected_at is not None:
        result = "answered"
    elif end and (m := ENDED.search(end[1])) and m.group(1) in DECLINED_REASONS:
        result = "declined"
    elif ring_timed_out:
        result = "no_answer"
    else:
        result = "failed"
    duration = 0
    if result == "answered":
        last = end[0] if end else events[-1][0]
        duration = max(0, round(last - connected_at))
    return {"result": result, "duration": duration, "detail": detail[:200]}


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


class Linphonec:
    """ログインしたまま常駐させる linphonec。標準入力にコマンドを書き、標準出力を行ごとに読む"""

    def __init__(self, user: str, password: str):
        if not user or not password:
            raise ValueError("PHONE_SIP_USER and PHONE_SIP_PASS are required")
        self.user = user
        self.password = password
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue = queue.Queue()

    def start(self) -> None:
        # 無いと linphone.db を開けないエラーが出る（通話はできる）
        (HOME / ".local/share/linphone").mkdir(parents=True, exist_ok=True)
        rc = HOME / "linphonerc"
        tmpl = string.Template((Path(__file__).parent / "linphonerc").read_text())
        body = tmpl.substitute(user=self.user, password=self.password)
        rc.unlink(missing_ok=True)
        fd = os.open(rc, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(body)
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(
            ["linphonec", "-c", str(rc)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
            # HOME が書けないと linphone.db を開けないエラーが出る
            env={**os.environ, "HOME": str(HOME)},
        )
        threading.Thread(target=self._read, args=(self.proc, self.lines), daemon=True).start()
        self.send("soundcard use files")

    def _read(self, proc: subprocess.Popen, lines: queue.Queue) -> None:
        for line in proc.stdout:
            lines.put((time.monotonic(), line))
            text = line.rstrip()
            if self.password not in text and "passwd" not in text.lower():
                print(f"linphonec: {text}", file=sys.stderr, flush=True)
        lines.put(None)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def ensure(self) -> None:
        if not self.alive():
            if self.proc is not None:
                print("linphonec exited, restarting", file=sys.stderr, flush=True)
            self.start()

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()

    def send(self, cmd: str) -> None:
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()

    def drain(self) -> None:
        while True:
            try:
                self.lines.get_nowait()
            except queue.Empty:
                return

    def next_line(self, timeout: float) -> tuple[float, str] | None:
        """timeout までに行が無ければ None。プロセスが終わっていれば EOFError"""
        try:
            item = self.lines.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            raise EOFError("linphonec exited")
        return item

    def registered(self, timeout: float) -> tuple[bool, str]:
        """起動直後はログインに数秒かかるので、status register を繰り返して待つ"""
        deadline = time.monotonic() + timeout
        last = "no reply to status register"
        while time.monotonic() < deadline:
            self.send("status register")
            until = time.monotonic() + 1
            while (left := until - time.monotonic()) > 0:
                item = self.next_line(left)
                if item is None:
                    continue
                if REGISTERED.search(item[1]):
                    return True, item[1].strip()
                if NOT_REGISTERED.search(item[1]):
                    last = item[1].strip()
        return False, f"not registered: {last}"

    def call(self, target: str, wav: Path, wav_seconds: float, ring_timeout: int) -> tuple[list, bool]:
        self.drain()
        self.send(f"play {wav}")
        self.send(f"call {target}")
        events: list[tuple[float, str]] = []
        started = time.monotonic()
        hangup_at = None
        terminated_at = None
        ring_timed_out = False
        while True:
            item = self.next_line(0.2)
            if item is not None:
                events.append(item)
                if ENDED.search(item[1]) or ERROR.search(item[1]):
                    return events, ring_timed_out
                if hangup_at is None and CONNECTED.search(item[1]):
                    hangup_at = item[0] + wav_seconds + 1
            now = time.monotonic()
            if terminated_at is None:
                if hangup_at is None and now - started > ring_timeout:
                    ring_timed_out = True
                    self.send("terminate")
                    terminated_at = now
                elif hangup_at is not None and now > hangup_at:
                    self.send("terminate")
                    terminated_at = now
            elif now - terminated_at > 10:
                # 終わった行が来ないまま。次の発信で起動し直す
                self.kill()
                return events, ring_timed_out


def do_call(lp: Linphonec, text: str, repeat: int) -> tuple[int, dict]:
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
        wav = tmp / "speech.wav"
        write_wav(wav, body)
        lp.ensure()
        ok, detail = lp.registered(timeout=15)
        if not ok:
            return 200, {"result": "failed", "duration": 0, "detail": detail[:200]}
        events, timed_out = lp.call(
            os.environ["PHONE_SIP_TARGET"], wav, wav_seconds, int(os.environ.get("PHONE_RING_TIMEOUT", "45"))
        )
        return 200, classify(events, timed_out)
    except Exception as e:
        print(f"call failed: {e!r}", file=sys.stderr)
        return 200, {"result": "failed", "duration": 0, "detail": repr(e)[:200]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _lock.release()


def make_handler(lp: Linphonec):
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
            self._send(*do_call(lp, text.strip(), repeat))

        def log_message(self, fmt, *args):
            print(fmt % args, file=sys.stderr)

    return Handler


def main():
    os.environ["PHONE_SIP_TARGET"]  # 未設定なら KeyError で起動しない
    # linphonec が linphonerc を書き戻す時も他人に読めないようにする
    os.umask(0o077)
    lp = Linphonec(os.environ["PHONE_SIP_USER"], os.environ["PHONE_SIP_PASS"])
    lp.start()
    port = int(os.environ.get("PHONE_HTTP_PORT", "8590"))
    ThreadingHTTPServer(("127.0.0.1", port), make_handler(lp)).serve_forever()


if __name__ == "__main__":
    main()
