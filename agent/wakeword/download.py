"""Download what training and evaluation need into WAKEWORD_DATA.

- openWakeWord's precomputed negative features (ACAV100M, ~17 GB) and its
  false-positive validation features
- MIT room impulse responses (reverb) and AudioSet clips (background noise)
- FLEURS ja: train/dev as real Japanese speech negatives, test for evaluation
- openWakeWord's melspectrogram and embedding models (into the venv)

Every file goes through a .part name, so a rerun resumes after a cut-off one.

    uv run --project agent/wakeword agent/wakeword/download.py
"""

import io
import json
import tarfile
import urllib.request

import numpy as np

from common import (
    ACAV_FEATURES,
    BACKGROUND_DIR,
    DOWNLOAD_DIR,
    FLEURS_DIR,
    RIR_DIR,
    SAMPLE_RATE,
    VALIDATION_FEATURES,
    log,
    write_wav,
)

HF = "https://huggingface.co/datasets"
FEATURES_URL = f"{HF}/davidscripka/openwakeword_features/resolve/main/"
RIR_REPO = "davidscripka/MIT_environmental_impulse_responses"
# One shard is 500 ten-second clips; two give ~2.8 h of noise, music and speech.
AUDIOSET_SHARDS = ("00", "01")
AUDIOSET_URL = f"{HF}/agkphysics/AudioSet/resolve/main/data/bal_train/"
FLEURS_URL = f"{HF}/google/fleurs/resolve/main/data/ja_jp/"
FLEURS_SPLITS = ("train", "dev", "test")


def fetch(url, path):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    log(f"downloading {url}")
    request = urllib.request.Request(url)
    if part.exists():
        request.add_header("Range", f"bytes={part.stat().st_size}-")
    with urllib.request.urlopen(request, timeout=60) as response:
        mode = "ab" if response.status == 206 else "wb"
        with part.open(mode) as f:
            while chunk := response.read(1 << 22):
                f.write(chunk)
    part.rename(path)
    return path


def resample(samples, rate):
    if rate == SAMPLE_RATE:
        return samples
    import torch
    import torchaudio

    return torchaudio.functional.resample(torch.from_numpy(samples), rate, SAMPLE_RATE).numpy()


def rirs():
    if any(RIR_DIR.glob("*.wav")):
        return
    with urllib.request.urlopen(f"https://huggingface.co/api/datasets/{RIR_REPO}/tree/main/16khz", timeout=60) as r:
        entries = json.load(r)
    for entry in entries:
        name = entry["path"].split("/")[-1]
        fetch(f"{HF}/{RIR_REPO}/resolve/main/16khz/{name}", RIR_DIR / name)


def audioset():
    import pyarrow.parquet as pq
    import soundfile

    for shard in AUDIOSET_SHARDS:
        done = BACKGROUND_DIR / f".audioset-{shard}"
        if done.exists():
            continue
        parquet = fetch(AUDIOSET_URL + f"{shard}.parquet", DOWNLOAD_DIR / f"audioset_bal_train_{shard}.parquet")
        table = pq.read_table(parquet, columns=["video_id", "audio"])
        for row in table.to_pylist():
            samples, rate = soundfile.read(io.BytesIO(row["audio"]["bytes"]), dtype="float32", always_2d=True)
            write_wav(BACKGROUND_DIR / f"{row['video_id']}.wav", resample(samples.mean(axis=1), rate))
        done.touch()
        parquet.unlink()


def fleurs():
    for split in FLEURS_SPLITS:
        fetch(FLEURS_URL + f"{split}.tsv", FLEURS_DIR / f"{split}.tsv")
        target = FLEURS_DIR / split
        if target.exists():
            continue
        archive = fetch(FLEURS_URL + f"audio/{split}.tar.gz", DOWNLOAD_DIR / f"fleurs_ja_{split}.tar.gz")
        part = target.with_name(split + ".part")
        part.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive) as tar:
            for member in tar:
                if member.isfile() and member.name.endswith(".wav"):
                    (part / member.name.split("/")[-1]).write_bytes(tar.extractfile(member).read())
        part.rename(target)
        archive.unlink()


def main():
    fetch(FEATURES_URL + ACAV_FEATURES.name, ACAV_FEATURES)
    fetch(FEATURES_URL + VALIDATION_FEATURES.name, VALIDATION_FEATURES)
    # Fail now rather than an hour into training if the big file is cut short.
    np.load(ACAV_FEATURES, mmap_mode="r")
    rirs()
    audioset()
    fleurs()

    import openwakeword.utils

    # A name matching no pretrained model: only the shared feature models come down.
    openwakeword.utils.download_models(model_names=["miku"])
    log("done")


if __name__ == "__main__":
    main()
