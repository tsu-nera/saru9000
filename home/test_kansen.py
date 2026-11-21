from datetime import date

import pytest

import kansen

# pdftotext -layout の出力の形（区名・市名・数値は架空）
TEXT = """\
                   令和８年１１月９日（月）～令和８年１１月１５日（日） 〔令和８年第４６週〕の感染症発生状況
罹患数・定点当たり罹患数、疾病、区別
集計対象：令和8年46週                                                    集計日：令和8年11月17日
架空市       急性呼吸器感染症             インフルエンザ            新型コロナウイルス感染症         ＲＳウイルス感染症
 男女合計    罹患数   定点当たり         罹患数    定点当たり          罹患数   定点当たり        罹患数    定点当たり
総数         5,594     91.70     543         8.90         48   0.79           12     0.32
東           1,227    153.38     106        13.25         12   1.50            -      -
西             624     78.00      80        10.00          -    -              2     0.40
他・不明           -       -         -          -            -    -              -      -
"""


def test_parse_ward_and_city():
    r = kansen.parse(TEXT, "西")
    assert r["week"] == "令和8年第46週"
    assert r["period"] == "令和8年11月9日（月）～令和8年11月15日（日）"
    assert r["ward"] == {"ari": 78.0, "flu": 10.0, "covid": 0.0}
    assert r["city"] == {"ari": 91.7, "flu": 8.9, "covid": 0.79}


def test_parse_rejects_changed_columns():
    with pytest.raises(ValueError, match="列"):
        kansen.parse(TEXT.replace("インフルエンザ", "インフル"), "西")


def test_parse_rejects_missing_ward():
    with pytest.raises(ValueError, match="南"):
        kansen.parse(TEXT, "南")


def test_candidates_are_last_two_iso_weeks():
    assert kansen.candidates(date(2026, 11, 22)) == [(8, 46), (8, 45)]
    # 年をまたぐと令和の年も変わる
    assert kansen.candidates(date(2027, 1, 12)) == [(9, 1), (8, 53)]
