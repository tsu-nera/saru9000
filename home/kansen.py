#!/usr/bin/env python3
"""市の感染症週報（PDF）から自宅の区の定点当たり報告数を読み、HA へ event で渡す（vaio の routine で回す）。

週報は火曜の夕方に前週（月〜日）分が出る。URL は令和の年2桁＋週2桁を埋める形で、古い号は消されるので
先週・先々週の順に探す。表は pdftotext -layout で文字として取れる。HA 側は home/packages/kansen.yaml が
event を受けて sensor にする（trigger-based template なので HA を再起動しても値が残る）。
URL の雛形（{year}{week} 入り）と区の名前は住所が分かるので .env の KANSEN_URL・KANSEN_WARD に置く。

    python3 home/kansen.py            # 取って HA へ送り、結果を JSON で出す
    python3 home/kansen.py --dry-run  # 送らずに出すだけ
    python3 home/kansen.py --check    # routine の check 用。送れたら exit 1（通知しない）、壊れたら exit 2
"""

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from ha import JST, rest, secret

EVENT = "saru9000_kansen_weekly"
# 区別の表の列（左から2列ずつ 罹患数・定点当たり）。並びが変わったら読まずに止める
DISEASES = [("ari", "急性呼吸器感染症"), ("flu", "インフルエンザ"), ("covid", "新型コロナウイルス感染症")]
TABLE_TITLE = "罹患数・定点当たり罹患数、疾病、区別"
FULLWIDTH = str.maketrans("０１２３４５６７８９", "0123456789")


def candidates(today: date) -> list[tuple[int, int]]:
    """先週・先々週の (令和の年, ISO 週)。週報の週は月〜日で ISO 週と同じ。"""
    out = []
    for k in (1, 2):
        y, w, _ = (today - timedelta(weeks=k)).isocalendar()
        out.append((y - 2018, w))
    return out


def fetch_pdf(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def pdf_text(pdf: bytes) -> str:
    return subprocess.run(["pdftotext", "-layout", "-", "-"], input=pdf, capture_output=True, check=True).stdout.decode()


def num(s: str) -> float:
    return 0.0 if s == "-" else float(s.replace(",", ""))


def parse(text: str, ward: str) -> dict:
    """週報のテキストから週・期間と、区と市全体の定点当たり報告数を取り出す。読めなければ ValueError。"""
    head = re.search(r"(令和\S+?日（.）～令和\S+?日（.）)\s*〔令和(.+?)年第(.+?)週〕", text)
    if not head:
        raise ValueError("週報の見出し（期間・週）が見つからない")
    lines = text.splitlines()
    try:
        i = next(n for n, l in enumerate(lines) if TABLE_TITLE in l)
    except StopIteration:
        raise ValueError("区別の表が見つからない") from None
    # 列見出しの行は「<市名>  急性呼吸器感染症  インフルエンザ ...」
    header = next((l for l in lines[i:i + 4] if DISEASES[0][1] in l), "")
    names = header.split()[1:]
    if names[:len(DISEASES)] != [n for _, n in DISEASES]:
        raise ValueError(f"区別の表の列が想定と違う: {names}")

    def row(label: str) -> dict:
        line = next((l for l in lines[i:i + 16] if l.split()[:1] == [label]), None)
        if line is None:
            raise ValueError(f"区別の表に「{label}」の行が無い")
        cells = line.split()[1:]
        return {key: num(cells[2 * n + 1]) for n, (key, _) in enumerate(DISEASES)}

    return {
        "week": f"令和{head.group(2).translate(FULLWIDTH)}年第{int(head.group(3).translate(FULLWIDTH))}週",
        "period": head.group(1).translate(FULLWIDTH),
        "ward": row(ward),
        "city": row("総数"),
    }


def latest(today: date, url_template: str, ward: str) -> tuple[str, dict] | None:
    for year, week in candidates(today):
        url = url_template.format(year=f"{year:02d}", week=f"{week:02d}")
        pdf = fetch_pdf(url)
        if pdf is not None:
            return url, parse(pdf_text(pdf), ward)
    return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    try:
        found = latest(datetime.now(JST).date(), secret("KANSEN_URL"), secret("KANSEN_WARD"))
        if found is None:
            # 先週分がまだ出ておらず、先々週分はもう消えた時。次の回に任せる
            print(json.dumps({"status": "not_published"}, ensure_ascii=False))
            sys.exit(1 if a.check else 0)
        url, r = found
        r["url"] = url
        if not a.dry_run:
            rest("POST", f"/api/events/{EVENT}", r)
    except (Exception, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code in (0, 1):
            raise
        print(f"kansen.py: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
    print(json.dumps(r, ensure_ascii=False))
    if a.check:
        sys.exit(1)


if __name__ == "__main__":
    main()
