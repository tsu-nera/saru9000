import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "phone"))

from server import classify  # noqa: E402

TARGET = "sip:user@sip.example.org;transport=udp"
RINGING = [
    f"call: connecting to '{TARGET}'..",
    "stream: audio: starting mediaenc 'srtp-mand' (wait_secure=0)",
    "call: SIP Progress: 110 Push sent (/)",
    "call: SIP Progress: 180 Ringing (/)",
]
ANSWERED = RINGING + [
    f"saru9000@192.0.2.10: Call answered: {TARGET}",
    "srtp: audio: SRTP is Enabled (cryptosuite=AES_CM_128_HMAC_SHA1_80)",
    "audio: Set audio encoder: PCMU 8000Hz 1ch",
    f"saru9000@192.0.2.10: Call established: {TARGET}",
    f"[0:00:05] audio=64000/0 (bit/s)    {TARGET}: session closed: Connection reset by peer [104]",
    f"sip:saru9000@192.0.2.10: Call with {TARGET} terminated (duration: 5 secs)",
    "ua: stop all (forced=0)",
]


def test_answered():
    r = classify(ANSWERED, False)
    assert r["result"] == "answered"
    assert r["duration"] == 5
    assert "terminated" in r["detail"]


def test_answered_ansi_and_newlines():
    lines = [f"\x1b[32m{x}\x1b[0m\n" for x in ANSWERED]
    assert classify(lines, False)["result"] == "answered"


def test_declined_603():
    lines = RINGING + [f"{TARGET}: session closed: 603 Decline"]
    r = classify(lines, False)
    assert r["result"] == "declined"
    assert "603 Decline" in r["detail"]


def test_declined_486():
    lines = RINGING + [f"{TARGET}: session closed: 486 Busy here"]
    assert classify(lines, False)["result"] == "declined"


def test_no_answer_ring_timeout():
    r = classify(RINGING, True)
    assert r["result"] == "no_answer"
    assert r["duration"] == 0


def test_no_answer_server_gave_up():
    lines = RINGING + [f"{TARGET}: session closed: 480 Temporarily Unavailable"]
    assert classify(lines, False)["result"] == "no_answer"
    lines = RINGING + [f"{TARGET}: session closed: 408 Request Timeout"]
    assert classify(lines, False)["result"] == "no_answer"


def test_failed_488():
    lines = RINGING[:2] + [f"{TARGET}: session closed: 488 Not acceptable here"]
    r = classify(lines, False)
    assert r["result"] == "failed"
    assert "488" in r["detail"]


def test_failed_function_not_implemented():
    lines = RINGING + [
        f"saru9000@192.0.2.10: Call answered: {TARGET}",
        f"{TARGET}: session closed: Function not implemented [38]",
    ]
    r = classify(lines, False)
    assert r["result"] == "failed"
    assert "[38]" in r["detail"]


def test_failed_empty():
    assert classify([], False) == {"result": "failed", "duration": 0, "detail": ""}


def test_stats_line_is_not_declined():
    lines = [
        f"[0:00:05] audio=64000/0 (bit/s)    {TARGET}: session closed: Connection reset by peer [104]",
        "saru9000@192.0.2.10:5070 603.486.1 10.0.486.603",
    ]
    assert classify(lines, False)["result"] == "failed"
