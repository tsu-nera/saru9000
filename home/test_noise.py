import io
import math
from array import array

import pytest

import noise


def pcm(samples: list[int]) -> bytes:
    return array("h", samples).tobytes()


def sine(amplitude: int) -> array:
    return array("h", (round(amplitude * math.sin(2 * math.pi * 1000 * i / noise.RATE)) for i in range(noise.RATE)))


def test_dbfs_sine():
    # RMS of a sine is amplitude / sqrt(2)
    assert noise.dbfs(sine(16384)) == pytest.approx(20 * math.log10(0.5 / math.sqrt(2)), abs=0.01)
    assert noise.dbfs(sine(32767)) == pytest.approx(-3.01, abs=0.01)


def test_dbfs_constant():
    assert noise.dbfs(array("h", [3277] * noise.RATE)) == pytest.approx(-20.0, abs=0.01)
    assert noise.dbfs(array("h", [-3277] * noise.RATE)) == pytest.approx(-20.0, abs=0.01)


def test_dbfs_silence_is_floor():
    assert noise.dbfs(array("h", [0] * noise.RATE)) == noise.FLOOR_DB
    assert noise.dbfs(array("h")) == noise.FLOOR_DB


def test_summarize_leq_is_energy_mean():
    # -10 dB and -30 dB: arithmetic mean is -20, energy mean is ~-12.96
    s = noise.summarize([-10.0, -30.0])
    assert s["leq"] == pytest.approx(10 * math.log10((0.1 + 0.001) / 2), abs=0.001)
    assert s["leq"] == pytest.approx(-12.96, abs=0.01)
    assert s["max"] == -10.0


def test_summarize_constant():
    s = noise.summarize([-40.0] * 60)
    assert s == pytest.approx({"leq": -40.0, "max": -40.0, "l90": -40.0})


def test_summarize_l90_is_lower_tenth():
    levels = [-float(i) for i in range(60)]  # 0 .. -59
    s = noise.summarize(levels)
    assert s["l90"] == -54.0  # 6th lowest of 60
    assert s["max"] == 0.0
    assert noise.summarize([-50.0] + [-20.0] * 9)["l90"] == -50.0


def test_measure_reports_every_minute_and_drops_partial():
    stream = io.BytesIO(pcm([3277] * noise.RATE * 3 + [0] * 100))
    posted = []
    noise.measure(stream, posted.append, seconds_per_report=1)
    assert len(posted) == 3
    assert posted[0]["leq"] == pytest.approx(-20.0, abs=0.01)


def test_measure_continues_after_post_failure(capsys):
    stream = io.BytesIO(pcm([3277] * noise.RATE * 2 + [0] * noise.RATE * 2))
    posted = []

    def post(summary):
        if not posted:
            posted.append(None)
            raise OSError("HA unreachable")
        posted.append(summary)

    noise.measure(stream, post, seconds_per_report=2)
    assert posted == [None, {"leq": noise.FLOOR_DB, "max": noise.FLOOR_DB, "l90": noise.FLOOR_DB}]
    assert "post failed" in capsys.readouterr().err
