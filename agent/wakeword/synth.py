"""Synthesize training clips with VOICEVOX into WAKEWORD_WORK/clips.

    positive_{train,test}/  「ミク」 alone, after 「ねえ」「OK」, and cut right after
                            「ミク」 when a request follows (「ミク、電気つけて」)
    negative_{train,test}/  words that sound like 「ミク」 (the ones ReazonSpeech
                            heard instead of it, and their neighbours) and 「サル」
    speech_train/           ordinary Japanese sentences (FLEURS ja train text)

Speakers, speed, pitch, intonation and accent vary per clip. The test split
uses styles never used for train, and the evaluation characters are left out
entirely (common.EVAL_CHARACTERS). Rerunning tops up each directory.

    uv run --project agent/wakeword agent/wakeword/synth.py --voicevox http://localhost:50121
"""

import argparse
import csv
import random
from concurrent.futures import ThreadPoolExecutor

from common import CLIP_DIR, FLEURS_DIR, SAMPLE_RATE, Voicevox, log, write_wav

REQUESTS = [
    "こんにちは", "電気つけて", "電気消して", "エアコンつけて", "エアコン消して", "今何時？",
    "明日の天気は？", "今日の予定は？", "自己紹介して", "音楽かけて", "踊って", "おはよう",
    "おやすみ", "いってきます", "ただいま", "カーテン開けて", "テレビつけて", "ありがとう",
    "何してるの？", "ちょっと聞いて", "タイマー三分", "寒いね", "暑いね", "元気？",
    "好きなものは？", "間接照明つけて", "天井灯つけて", "静かにして", "もう一回", "聞こえる？",
]

# 「ミク」 as a bare call, with what people put in front of it, and before a request.
POSITIVE_FORMS = ["ミク", "ミク。", "ミク！", "ミク？", "ミクー", "ねえミク", "ねえ、ミク", "OKミク", "ミク、{}", "ねえミク、{}"]

# The words ReazonSpeech turned 「ミク」 into, plus near neighbours by one mora.
SIMILAR = [
    "ミック", "二区", "陸", "見て", "水", "ミコ", "肉", "ミルク", "未来", "ミキ", "ミカ", "ミツ",
    "ミス", "ミント", "右", "三日", "見た", "見る", "耳", "道", "店", "皆", "短く", "ニック",
    "ピク", "ビク", "チク", "リク", "キク", "菊", "地区", "北区", "六", "行く", "聞く", "引く",
    "敷く", "遠く", "少し", "ニコ", "ミニ", "ミル", "ミン", "ミケ", "メク", "ムク", "マク",
    "ミラ", "ミサ", "ミチ", "ミナ", "ミホ", "見えた", "身近", "未熟", "宮", "みかん", "ミシン",
]
# The other wake words saru uses; its owner says these to other characters.
OTHERS = ["サル", "OKサル", "ねえサル", "サルさん", "サル、{}", "OKサル、{}", "ねえ", "OK"]
NEGATIVE_FORMS = SIMILAR + [w + "、{}" for w in SIMILAR[:20]] + OTHERS

COUNTS = {"positive_train": 5000, "positive_test": 500, "negative_train": 4000, "negative_test": 400, "speech_train": 600}
# Share of styles held out for the test split.
TEST_STYLE_SHARE = 0.15
# A little of what follows 「ミク」 stays in the cut, as in natural speech.
CUT_TAIL = (0.0, 0.12)


def moras_until_miku(query):
    """Seconds from the start of the synthesized audio to the end of the first 「ミク」, or None."""
    t = query["prePhonemeLength"]
    previous = None
    for phrase in query["accent_phrases"]:
        moras = phrase["moras"] + ([phrase["pause_mora"]] if phrase.get("pause_mora") else [])
        for mora in moras:
            t += (mora["consonant_length"] or 0) + mora["vowel_length"]
            if previous == "ミ" and mora["text"] == "ク":
                return t / query["speedScale"]
            previous = mora["text"]
    return None


def vary(voicevox, query, style, rng):
    # A two-mora 「ミク」 phrase comes as head-high (ミ\ク); people also say it flat.
    for phrase in query["accent_phrases"]:
        if [m["text"] for m in phrase["moras"]] == ["ミ", "ク"] and rng.random() < 0.4:
            phrase["accent"] = 2
            query["accent_phrases"] = voicevox.mora_pitch(query["accent_phrases"], style)
            break
    query.update(
        speedScale=rng.uniform(0.8, 1.35),
        pitchScale=rng.uniform(-0.08, 0.08),
        intonationScale=rng.uniform(0.6, 1.5),
        volumeScale=rng.uniform(0.7, 1.3),
        prePhonemeLength=rng.uniform(0.05, 0.3),
        postPhonemeLength=rng.uniform(0.05, 0.3),
    )
    return query


def make(voicevox, kind, text, style, rng):
    query = vary(voicevox, voicevox.query(text, style), style, rng)
    audio = voicevox.synthesize(query, style)
    if kind.startswith("positive") and "、" in text and not text.startswith("ねえ、"):
        end = moras_until_miku(query)
        if end is None:
            raise ValueError(f"no ミク in the query for {text!r}")
        audio = audio[: int((end + rng.uniform(*CUT_TAIL)) * SAMPLE_RATE)]
    return audio


def texts_for(kind, rng, n):
    if kind == "speech_train":
        with open(FLEURS_DIR / "train.tsv", newline="") as f:
            sentences = sorted({row[2] for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE) if "ミク" not in row[2]})
        rng.shuffle(sentences)
        return sentences[:n]
    forms = POSITIVE_FORMS if kind.startswith("positive") else NEGATIVE_FORMS
    return [rng.choice(forms).format(rng.choice(REQUESTS)) for _ in range(n)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voicevox", default="http://vaio:50021")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--scale", type=float, default=1.0, help="multiply every count (for a quick trial)")
    args = parser.parse_args()

    voicevox = Voicevox(args.voicevox)
    styles = voicevox.talk_styles()
    random.Random(0).shuffle(styles)
    n_test = max(1, int(len(styles) * TEST_STYLE_SHARE))
    split = {"test": [s for s, _ in styles[:n_test]], "train": [s for s, _ in styles[n_test:]]}
    log(f"{len(styles)} styles: {len(split['train'])} train, {len(split['test'])} test")

    for kind, count in COUNTS.items():
        target = CLIP_DIR / kind
        target.mkdir(parents=True, exist_ok=True)
        have = len(list(target.glob("*.wav")))
        need = int(count * args.scale) - have
        if need <= 0:
            continue
        rng = random.Random(f"{kind}-{have}")
        jobs = [
            (have + i, text, rng.choice(split[kind.rsplit("_", 1)[1]]), random.Random(f"{kind}-{have + i}"))
            for i, text in enumerate(texts_for(kind, rng, need))
        ]

        def run(job):
            index, text, style, job_rng = job
            name = f"{index:05d}_{style}.wav"
            write_wav(target / name, make(voicevox, kind, text, style, job_rng))
            return f"{name}\t{style}\t{text}\n"

        # What each clip says, for listening to the odd one out.
        with ThreadPoolExecutor(args.jobs) as pool, (target / "manifest.tsv").open("a") as manifest:
            for done, line in enumerate(pool.map(run, jobs), 1):
                manifest.write(line)
                if done % 500 == 0:
                    log(f"{kind}: {done}/{need}")
        log(f"{kind}: {need} clips")


if __name__ == "__main__":
    main()
