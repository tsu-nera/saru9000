"""Score MODEL_PATH on the recordings from vaio and FLEURS ja test.

    positive   rec-1030-1404/c270: 50 「ミク、…」 played from the Nest, recorded on the C270
    mic false  rec-1030-1326/c270 (20 FLEURS sentences) and the 「サル」「OKサル」 phrases
               of rec-1030-1444/c270; neither contains 「ミク」
    long       every FLEURS ja test sentence back to back, for false activations per hour
    (info)     the 「ねえミク」「ミクさん」「ミクちゃん」「初音ミク」 (rec-1030-1425) and
               「OKミク」 (rec-1030-1444) recordings, not part of the target

Audio is fed in 80 ms chunks as openWakeWord does live. Prints the counts for
every threshold and the threshold chosen: the most positives with no mic false
activation and at most TARGET_PER_HOUR on the long run (the higher threshold on
a tie).

    uv run --project agent/wakeword agent/wakeword/evaluate.py
"""

import argparse
import csv
import json

import numpy as np

from common import BENCH_DIR, FLEURS_DIR, MODEL_PATH, SAMPLE_RATE, log, read_wav

CHUNK = 1280
# One spoken call can keep the score high for several chunks; count it once.
REFRACTORY_SECONDS = 2.0
# Silence after each clip so a call at its very end still gets scored.
TAIL_SECONDS = 1.0
# Between FLEURS sentences in the long run.
GAP_SECONDS = 0.3
THRESHOLDS = [round(t, 2) for t in np.arange(0.05, 1.0, 0.05)] + [0.97, 0.99]
TARGET_POSITIVES = 45
TARGET_PER_HOUR = 1.0


def bench_set(recording, script):
    """[(wav path, text)] of a recording, from the script it was played from."""
    with open(BENCH_DIR / script / "set.tsv", newline="") as f:
        rows = list(csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE))
    return [(BENCH_DIR / recording / "c270" / row[0], row[3]) for row in rows]


def scores(model, audio):
    """Per-chunk scores for 16-bit samples."""
    model.reset()
    pcm = np.concatenate([audio, np.zeros(int(TAIL_SECONDS * SAMPLE_RATE), np.float32)])
    pcm = (pcm * 32767).astype(np.int16)
    out = []
    for start in range(0, len(pcm) - CHUNK + 1, CHUNK):
        # One model loaded, so one score per chunk (keyed by the file name).
        (score,) = model.predict(pcm[start : start + CHUNK]).values()
        out.append(score)
    return np.array(out)


def activations(score, threshold):
    count, last = 0, -np.inf
    for i in np.flatnonzero(score >= threshold):
        if (i - last) * CHUNK / SAMPLE_RATE >= REFRACTORY_SECONDS:
            count += 1
        last = i
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=str(MODEL_PATH))
    args = parser.parse_args()

    from openwakeword.model import Model

    model = Model(wakeword_models=[args.model], inference_framework="onnx")

    def peak(items):
        return [(text, float(scores(model, read_wav(path)).max())) for path, text in items]

    positive = peak(bench_set("rec-1030-1404", "cmd"))
    assert len(positive) == 50 and all(text.startswith("ミク") for text, _ in positive)
    with open(BENCH_DIR / "fleurs" / "set.tsv", newline="") as f:
        fleurs20 = [(BENCH_DIR / "rec-1030-1326" / "c270" / row[0], row[3]) for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)]
    cmd3 = bench_set("rec-1030-1444", "cmd3")
    saru = [(p, t) for p, t in cmd3 if "ミク" not in t]
    mic_false = peak(fleurs20) + peak(saru)
    info = {"ねえミク等 (1425)": peak(bench_set("rec-1030-1425", "cmd2")), "OKミク (1444)": peak([(p, t) for p, t in cmd3 if "ミク" in t])}
    log(f"positive {len(positive)}, mic false {len(fleurs20)} FLEURS + {len(saru)} サル")

    with open(BENCH_DIR / "fleurs" / "test.tsv", newline="") as f:
        names = [row[1] for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)]
    gap = np.zeros(int(GAP_SECONDS * SAMPLE_RATE), np.float32)
    long_audio = np.concatenate([part for name in names for part in (read_wav(FLEURS_DIR / "test" / name), gap)])
    hours = len(long_audio) / SAMPLE_RATE / 3600
    log(f"long run: {len(names)} sentences, {hours:.2f} h")
    long_score = scores(model, long_audio)

    rows = []
    for t in THRESHOLDS:
        n_long = activations(long_score, t)
        rows.append({
            "threshold": t,
            "positive": sum(s >= t for _, s in positive),
            "mic_false_fleurs": sum(s >= t for _, s in mic_false[: len(fleurs20)]),
            "mic_false_saru": sum(s >= t for _, s in mic_false[len(fleurs20) :]),
            "long_false": n_long,
            "long_per_hour": round(n_long / hours, 2),
            **{k: sum(s >= t for _, s in v) for k, v in info.items()},
        })

    header = list(rows[0])
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for r in rows:
        print("| " + " | ".join(str(r[k]) for k in header) + " |")

    ok = [r for r in rows if r["mic_false_fleurs"] + r["mic_false_saru"] == 0 and r["long_per_hour"] <= TARGET_PER_HOUR]
    chosen = max(ok, key=lambda r: (r["positive"], r["threshold"])) if ok else None
    print()
    print(f"long run: {len(names)} sentences, {hours:.2f} h")
    print("missed positives at chosen threshold:" if chosen else "no threshold meets the false activation targets")
    if chosen:
        for text, s in positive:
            if s < chosen["threshold"]:
                print(f"  {s:.3f} {text}")
    print(json.dumps({"chosen": chosen, "target_met": bool(chosen and chosen["positive"] >= TARGET_POSITIVES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
