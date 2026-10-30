"""Train the 「ミク」 detector with openWakeWord's training code and write MODEL_PATH.

The steps of openWakeWord's automatic training notebook, with the clips from
synth.py in place of its English Piper TTS clips:

1. augment the clips (EQ, distortion, pitch, noise, AudioSet background, MIT
   room reverb) and turn them into openWakeWord features
2. add real Japanese speech (FLEURS ja train/dev) as negative features
3. openwakeword.train.Model.auto_train against those plus the ACAV100M
   negative features, choosing checkpoints on openWakeWord's validation set
4. export ONNX

Features are cached in WAKEWORD_WORK/features; delete that directory (or pass
--refeature) after changing the clips.

    uv run --project agent/wakeword agent/wakeword/train.py
"""

import argparse
import functools
import logging
import shutil
import tempfile
from pathlib import Path

import numpy as np

from common import (
    ACAV_FEATURES,
    BACKGROUND_DIR,
    CLIP_DIR,
    FEATURE_DIR,
    FLEURS_DIR,
    MODEL_PATH,
    RIR_DIR,
    SAMPLE_RATE,
    VALIDATION_FEATURES,
    log,
    read_wav,
    write_wav,
)

# openWakeWord sizes clips as the median positive + 0.75 s with a 2 s floor;
# 「ミク」 clips are about 1 s, so it is the floor.
TOTAL_LENGTH = 2 * SAMPLE_RATE
# 2 s of audio gives 16 embedding frames of 80 ms: the model's input.
FRAMES = 16
# Each synthesized clip goes through augmentation this many times.
AUGMENTATION_ROUNDS = {"positive_train": 3, "positive_test": 1, "negative_train": 2, "negative_test": 1, "speech_chunks": 1}
# Hop between windows taken from long real speech (frames of 80 ms).
SPEECH_HOP = 4
FEATURE_CPUS = 8


def clips(kind):
    return sorted(str(p) for p in (CLIP_DIR / kind).glob("*.wav"))


def chunk_sentences():
    """Cut the synthesized sentences into 2 s clips (augment_clips keeps only the first 2 s of a longer one)."""
    target = CLIP_DIR / "speech_chunks"
    if target.exists():
        return
    part = Path(tempfile.mkdtemp(dir=CLIP_DIR))
    for path in clips("speech_train"):
        audio = read_wav(path)
        for i, start in enumerate(range(0, max(len(audio) - TOTAL_LENGTH // 2, 1), TOTAL_LENGTH)):
            write_wav(part / f"{Path(path).stem}_{i}.wav", audio[start : start + TOTAL_LENGTH])
    part.rename(target)


def augmented_features(kind, background, rirs):
    from openwakeword.data import augment_clips
    from openwakeword.utils import compute_features_from_generator

    output = FEATURE_DIR / f"{kind}.npy"
    if output.exists():
        return output
    paths = clips(kind) * AUGMENTATION_ROUNDS[kind]
    log(f"{kind}: augmenting {len(paths)} clips")
    generator = augment_clips(paths, total_length=TOTAL_LENGTH, batch_size=128, background_clip_paths=background, RIR_paths=rirs)
    part = output.with_name(output.stem + ".part.npy")
    compute_features_from_generator(generator, n_total=len(paths), clip_duration=TOTAL_LENGTH, output_file=str(part), ncpu=FEATURE_CPUS)
    part.rename(output)
    return output


def fleurs_features():
    """Windows of real Japanese read speech, every SPEECH_HOP frames, as negatives."""
    from openwakeword.utils import AudioFeatures

    output = FEATURE_DIR / "fleurs.npy"
    if output.exists():
        return output
    features = AudioFeatures(ncpu=FEATURE_CPUS)
    windows = []
    for split in ("train", "dev"):
        paths = sorted((FLEURS_DIR / split).glob("*.wav"))
        log(f"fleurs {split}: {len(paths)} utterances")
        for path in paths:
            pcm = (read_wav(path) * 32767).astype(np.int16)
            embedding = features._get_embeddings(pcm)
            windows.extend(embedding[i : i + FRAMES] for i in range(0, len(embedding) - FRAMES + 1, SPEECH_HOP))
    part = output.with_name(output.stem + ".part.npy")
    np.save(part, np.array(windows, dtype=np.float32))
    part.rename(output)
    return output


def make_features():
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    chunk_sentences()
    background = sorted(str(p) for p in BACKGROUND_DIR.glob("*.wav"))
    rirs = sorted(str(p) for p in RIR_DIR.glob("*.wav"))
    files = {kind: augmented_features(kind, background, rirs) for kind in AUGMENTATION_ROUNDS}
    files["fleurs"] = fleurs_features()
    return files


def train(files, args):
    import torch
    from openwakeword.data import mmap_batch_generator
    from openwakeword.train import Model

    def windows(x):
        # ACAV100M rows are already 16 frames; this only reshapes when they are not (as openWakeWord's train.py).
        if x.shape[1] == FRAMES:
            return x
        x = np.vstack(x)
        return np.array([x[i : i + FRAMES] for i in range(0, x.shape[0] - FRAMES, FRAMES)])

    data = {
        "positive": files["positive_train"],
        "adversarial": files["negative_train"],
        "speech_tts": files["speech_chunks"],
        "speech_real": files["fleurs"],
        "ACAV100M": ACAV_FEATURES,
    }
    n_per_class = {"positive": 256, "adversarial": 128, "speech_tts": 128, "speech_real": 256, "ACAV100M": 1024}
    generator = mmap_batch_generator(
        {k: str(v) for k, v in data.items()},
        n_per_class=n_per_class,
        data_transform_funcs={"ACAV100M": windows},
        label_transform_funcs={k: (lambda y, p=(k == "positive"): [int(p)] * len(y)) for k in data},
    )

    class Batches(torch.utils.data.IterableDataset):
        def __iter__(self):
            return generator

    def as_float(batch):
        x, y = batch
        return torch.from_numpy(x.astype(np.float32)), torch.from_numpy(y.astype(np.float32))

    X_train = torch.utils.data.DataLoader(Batches(), batch_size=None, num_workers=0, collate_fn=as_float)

    class FalsePositiveWindows:
        """Every 16-frame window of the validation features, a slice at a time.

        openWakeWord's train.py builds all ~480k windows at once (3 GB) and
        sends them to the GPU in one batch; with VOICEVOX loaded, mouse runs
        out of memory.
        """

        def __init__(self, path, batch=32768):
            frames = np.load(path)
            self.windows = np.lib.stride_tricks.sliding_window_view(frames, (FRAMES, frames.shape[1]))[:, 0]
            self.batch = batch

        def __iter__(self):
            for start in range(0, len(self.windows), self.batch):
                x = torch.from_numpy(np.ascontiguousarray(self.windows[start : start + self.batch]))
                yield x, torch.zeros(len(x))

    X_val_fp = FalsePositiveWindows(VALIDATION_FEATURES)
    pos, neg = np.load(files["positive_test"]), np.load(files["negative_test"])
    X_val = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(
            torch.from_numpy(np.vstack((pos, neg))),
            torch.from_numpy(np.hstack((np.ones(len(pos)), np.zeros(len(neg)))).astype(np.float32)),
        ),
        batch_size=len(pos) + len(neg),
    )

    model = Model(n_classes=1, input_shape=(FRAMES, 96), model_type="dnn", layer_dim=args.layer_size,
                  seconds_per_example=1280 * FRAMES / SAMPLE_RATE)
    best = model.auto_train(X_train=X_train, X_val=X_val, false_positive_val_data=X_val_fp, steps=args.steps,
                            max_negative_weight=args.max_negative_weight, target_fp_per_hour=args.target_fp_per_hour)
    with tempfile.TemporaryDirectory() as tmp:
        model.export_model(model=best, model_name="miku", output_dir=tmp)
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(Path(tmp) / "miku.onnx", MODEL_PATH)
    log(f"wrote {MODEL_PATH}")


def main():
    parser = argparse.ArgumentParser()
    # Defaults are openWakeWord's example training config (examples/custom_model.yml).
    parser.add_argument("--steps", type=int, default=50000)
    parser.add_argument("--layer-size", type=int, default=32)
    parser.add_argument("--max-negative-weight", type=float, default=1500)
    parser.add_argument("--target-fp-per-hour", type=float, default=0.2)
    parser.add_argument("--refeature", action="store_true", help="recompute the cached features")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    import torchaudio

    # openWakeWord and torch-audiomentations read clips through torchaudio,
    # whose default sox backend segfaults against mouse's libsox.
    for name in ("load", "info"):
        setattr(torchaudio, name, functools.partial(getattr(torchaudio, name), backend="soundfile"))

    if args.refeature:
        shutil.rmtree(FEATURE_DIR, ignore_errors=True)
        shutil.rmtree(CLIP_DIR / "speech_chunks", ignore_errors=True)
    train(make_features(), args)


if __name__ == "__main__":
    main()
