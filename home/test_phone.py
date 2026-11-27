import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "phone"))

from server import classify  # noqa: E402

TARGET = "sip:user@sip.example.org"
# 11-27 に linphonec 5.1.65 で見た行（プロンプトがくっついた行・コマンドのエコーを含む）
RINGING = [
    f"linphonec> call {TARGET}",
    f"Call 3 to {TARGET} in progress.",
    f"Call 3 to {TARGET} ringing.",
]


def timed(lines: list[str], start: float = 100.0, step: float = 1.0) -> list[tuple[float, str]]:
    return [(start + i * step, x) for i, x in enumerate(lines)]


def test_answered():
    events = timed(RINGING) + [
        (110.0, f"Call 3 with {TARGET} connected.\n"),
        (124.4, f"Call 3 with {TARGET} ended (No error).\n"),
    ]
    r = classify(events, False)
    assert r == {"result": "answered", "duration": 14, "detail": f"Call 3 with {TARGET} ended (No error)."}


def test_answered_with_prompt_prefix():
    events = timed(RINGING + [f"linphonec> Call 3 with {TARGET} connected.", f"Call 3 with {TARGET} ended (No error)."])
    assert classify(events, False)["result"] == "answered"


def test_answered_without_end_line():
    events = timed(RINGING) + [(110.0, f"Call 3 with {TARGET} connected."), (118.0, "linphonec> terminate")]
    r = classify(events, False)
    assert r["result"] == "answered"
    assert r["duration"] == 8


def test_no_answer_ring_timeout():
    events = timed(RINGING + ["linphonec> terminate", f"Call 3 with {TARGET} ended (No error)."])
    r = classify(events, True)
    assert r["result"] == "no_answer"
    assert r["duration"] == 0


def test_declined():
    # linphone_reason_to_string(LinphoneReasonDeclined)。603 だけは呼び出し中でも ended になる（liblinphone 5.1.65 の call-session.cpp）
    events = timed(RINGING + [f"Call 3 with {TARGET} ended (Call declined)."])
    r = classify(events, False)
    assert r["result"] == "declined"
    assert "Call declined" in r["detail"]


def test_failed_error():
    events = timed(RINGING + [f"Call 3 with {TARGET} error."])
    r = classify(events, False)
    assert r["result"] == "failed"
    assert r["detail"] == f"Call 3 with {TARGET} error."


def test_failed_empty():
    assert classify([], False) == {"result": "failed", "duration": 0, "detail": ""}
