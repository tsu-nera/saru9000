#!/usr/bin/env python3
"""Plugin_AnyScript bridge that connects MMDAgent-EX voice dialog to Claude Code headless mode.

Reads RECOG_EVENT_STOP|<text> lines from stdin (speech recognition results),
calls `claude -p` to get a response, and writes SYNTH_START|<model>|<voice>|<text>
lines to stdout (speech synthesis requests).

Run under MMDAgent-EX via Plugin_AnyScript_Command, e.g.:
    Plugin_AnyScript_Command=python3 -u /path/to/claude_bridge.py

The `-u` flag is required: without unbuffered stdio, MMDAgent-EX never sees
the synthesized speech because Python buffers stdout when it is a pipe.
"""

import os
import shutil
import subprocess
import sys
import threading
import uuid

MODEL_ALIAS = "0"
VOICE = "mei_voice_normal"
CLAUDE_TIMEOUT_SEC = 60
MAX_SPEECH_LEN = 300

# Julius returns punctuation-only results (e.g. "。") for ambient noise. Each one
# would otherwise cost a multi-second claude call that blocks the next input.
NON_SPEECH_CHARS = "。、，．・？！?!,. \t　"
MIN_SPEECH_LEN = 2

FALLBACK_SPEECH = "ごめんなさい、うまく考えられませんでした"

DEFAULT_PERSONA = (
    "あなたは3Dキャラクター「ミク」です。音声で短く日本語で話し言葉で答えてください。"
    "記号や絵文字、URLは使わないでください。"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERSONA_PATH = os.path.join(SCRIPT_DIR, "persona.txt")


def load_persona():
    """Load the persona system prompt from persona.txt, falling back to a default."""
    try:
        with open(PERSONA_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    except OSError as e:
        print(f"[claude_bridge] failed to read persona.txt: {e}", file=sys.stderr)
    return DEFAULT_PERSONA


def build_subprocess_env():
    """Build the subprocess environment without ANTHROPIC_API_KEY.

    This forces `claude -p` to use the Claude Code subscription login instead
    of falling back to metered API-key billing.
    """
    return {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}


def sanitize_speech(text):
    """Sanitize a Claude response for speech synthesis output."""
    if text is None:
        return ""
    # Collapse newlines into a single line, joined with a Japanese period.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    collapsed = "。".join(lines)
    # '|' is the MMDAgent message field separator; strip it.
    collapsed = collapsed.replace("|", "")
    collapsed = collapsed.strip()
    if len(collapsed) > MAX_SPEECH_LEN:
        collapsed = collapsed[:MAX_SPEECH_LEN]
    return collapsed


def is_speech(text):
    """Return True if a recognition result carries enough content to answer."""
    return len([c for c in text if c not in NON_SPEECH_CHARS]) >= MIN_SPEECH_LEN


def emit_speech(text):
    """Print a SYNTH_START message for MMDAgent-EX to speak."""
    print(f"SYNTH_START|{MODEL_ALIAS}|{VOICE}|{text}", flush=True)


class ClaudeSession:
    """Manages a single Claude Code headless-mode conversation session."""

    def __init__(self):
        self.claude_path = shutil.which("claude")
        self.session_id = str(uuid.uuid4())
        self.first_call = True
        self.persona = load_persona()
        self.env = build_subprocess_env()

    def _run_claude(self, text, args):
        cmd = [self.claude_path, "-p", text] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SEC,
            env=self.env,
            # MMDAgent-EX keeps writing messages to this process's stdin, so an
            # inherited stdin never reaches EOF: claude would wait on it forever
            # and swallow the recognition lines meant for us.
            stdin=subprocess.DEVNULL,
        )

    def ask(self, text):
        """Send text to Claude and return the sanitized speech response.

        Returns None if the call failed and the caller should speak a fallback.
        """
        if self.claude_path is None:
            print("[claude_bridge] claude executable not found on PATH", file=sys.stderr)
            return None

        if self.first_call:
            args = ["--session-id", self.session_id, "--append-system-prompt", self.persona]
        else:
            args = ["--resume", self.session_id, "--append-system-prompt", self.persona]

        try:
            result = self._run_claude(text, args)
        except subprocess.TimeoutExpired:
            print("[claude_bridge] claude call timed out", file=sys.stderr)
            return None
        except OSError as e:
            print(f"[claude_bridge] failed to launch claude: {e}", file=sys.stderr)
            return None

        if result.returncode != 0:
            print(
                f"[claude_bridge] claude exited with {result.returncode}: {result.stderr.strip()}",
                file=sys.stderr,
            )
            if not self.first_call:
                # --resume may fail if the session is gone; retry once with a fresh session.
                print("[claude_bridge] retrying with a new session id", file=sys.stderr)
                self.session_id = str(uuid.uuid4())
                self.first_call = True
                return self.ask(text)
            return None

        self.first_call = False
        return sanitize_speech(result.stdout)


class LatestInput:
    """Holds the most recent recognition result, discarding older ones.

    A claude call takes several seconds, and MMDAgent-EX keeps sending messages
    throughout. Answering a queued backlog one by one would put the character
    minutes behind the conversation, so only the newest utterance survives.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._text = None
        self._closed = False

    def put(self, text):
        with self._cond:
            if self._text is not None:
                print(f"[claude_bridge] dropped stale input: {self._text}", file=sys.stderr)
            self._text = text
            self._cond.notify()

    def close(self):
        with self._cond:
            self._closed = True
            self._cond.notify()

    def get(self):
        """Block until an input arrives; return None once stdin is closed."""
        with self._cond:
            while self._text is None and not self._closed:
                self._cond.wait()
            text, self._text = self._text, None
            return text


def read_recognitions(latest):
    """Drain stdin continuously so MMDAgent-EX never blocks writing to us."""
    for line in sys.stdin:
        line = line.rstrip("\n")
        if not line.startswith("RECOG_EVENT_STOP|"):
            continue

        text = line[len("RECOG_EVENT_STOP|"):].strip()
        if not text:
            continue

        print(f"[claude_bridge] recognized: {text}", file=sys.stderr)

        if not is_speech(text):
            print("[claude_bridge] ignored as non-speech noise", file=sys.stderr)
            continue

        latest.put(text)

    latest.close()


def main():
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    print("[claude_bridge] started", file=sys.stderr)

    session = ClaudeSession()
    if session.claude_path is None:
        print("[claude_bridge] warning: claude executable not found on PATH at startup", file=sys.stderr)

    latest = LatestInput()
    threading.Thread(target=read_recognitions, args=(latest,), daemon=True).start()

    while True:
        text = latest.get()
        if text is None:
            break

        speech = session.ask(text)
        if not speech:
            speech = FALLBACK_SPEECH

        emit_speech(speech)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass
