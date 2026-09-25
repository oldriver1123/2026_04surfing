"""
scorer.py
初級者（横にすべる練習中）× ミッドレングス（7.8ft）向けサーフィン適性スコアリング

想定ユーザー像:
  - サーフィンレベル: 初級者（ホワイトウォーターは卒業し、横にすべる練習中）
  - ボード: ミッドレングス 7.8ft（ボリュームがあり波を掴みやすく安定感がある）

重み配分:
  波高40% / 風30% / 周期20% / 潮10%
  混雑・天気は参考情報のみ（総合点には含めない）

鵠沼（スケートパーク前）は南向きビーチ:
  - オフショア（良）: 北風  = 315〜45°
  - サイドオフ:       北東・北西 = 45〜90° / 270〜315°
  - サイドオン:       東・西    = 90〜135° / 225〜270°
  - オンショア（悪）: 南風  = 135〜225°
"""

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime
from math import cos, pi

import jpholiday


@dataclass
class SurfScore:
    total: int                # 総合スコア (0-100)
    wave_condition_score: int # 波の状態スコア（風・周期・波高の合成、内訳表示用）
    wave_score: int           # 波高スコア
    period_score: int         # 周期スコア
    period_label: str         # 周期の説明
    wind_score: int           # 風スコア
    weather_score: int        # 天気スコア
    crowd_score: int          # 混雑スコア
    crowd_label: str          # 混雑度ラベル
    risk_note: str             # クローズアウト等の注意書き（該当なしなら空文字）
    crowd_caution: bool         # 好条件で上級者が集まりやすいことへの注意フラグ
    decision: str                # 行くべきか（◎行くべき / △要注意 / ✕見送り推奨）
    rating: str                # ★評価
    comment: str                # 一言コメント
    wave_label: str             # 波の大きさ説明
    wind_label: str             # 風の種類
    tide_score: int = 50        # 潮の適性（未判定時は暫定50点）
    tide_label: str = "未判定・暫定50点"


# ---------- 個別スコア ----------

def _score_wave_height(h: float) -> tuple[int, str]:
    """
    波高スコアと説明（有義波高 Hs）
    モデルの有義波高を岸で崩れる波のサイズへ直接換算しない。
    0.35m以下は小波不足、0.45m以下は要確認とする暫定的な個人向け基準。
    """
    if h <= 0.2:
        return 0,   "波が非常に小さい予報（練習できる波は期待薄）"
    elif h <= 0.35:
        return 15,  "小さく弱い予報（横に走る練習は期待薄）"
    elif h <= 0.45:
        return 40,  "小波予報（乗れる波か現地確認が必要）"
    elif h <= 0.6:
        return 100, "練習候補の波高（実際の割れ方は現地確認）"
    elif h < 0.9:
        return 45,  "やや大きめの予報（風・周期などが良ければ練習候補）"
    else:
        return 0,   "大きすぎる（サーフィン不可）"


def _score_wave_period(p: float) -> tuple[int, str]:
    """
    波の周期スコアと説明
    実体験を踏まえ、5〜8秒を理想的な周期とする。
    """
    if p <= 0:
        return 0,   "データなし"
    elif p < 4:
        return 30,  "短すぎる（面が乱れやすい）"
    elif p < 5:
        return 70,  "やや短め"
    elif p <= 8:
        return 100, "採点上の適正範囲（波の強さ・割れ方は別途確認）"
    elif p <= 10:
        return 70,  "やや長め"
    elif p <= 13:
        return 50,  "長め（パワフル）"
    else:
        return 30,  "非常に長い（威力が強くタイミング注意）"


def _closeout_risk(swell_period: float, wave_period: float, height: float) -> tuple[float, str]:
    """
    うねり本来の周期（swellPeriod）に対して合成周期（wavePeriod）が
    大きく短い場合、うねりに別の短周期の波（風波や副次的なうねり）が
    重なって海面が乱れている可能性が高い。
    複数の周期の波が重なるとタイミングにより波が急に大きくなったり
    予測しづらく崩れたりしやすいため、このギャップが大きいほど
    「波が乱れやすい」ものとして波の状態スコアを減点する。
    波高が小さいうちは乱れていても実害が小さいため対象外とする。
    """
    if height < 0.4:
        return 1.0, ""

    gap = swell_period - wave_period
    if gap >= 4:
        return 0.6, (
            f"うねり周期{swell_period:.0f}秒に対し合成周期{wave_period:.0f}秒と短く、"
            "波が複数混ざって不規則・急に崩れやすい状態"
        )
    elif gap >= 2:
        return 0.8, "うねりに短周期の波が混ざり、やや波が乱れやすい状態"
    else:
        return 1.0, ""


def _score_wind(speed: float, direction: float) -> tuple[int, str]:
    """
    風速・風向スコアと種別ラベル
    横にすべる練習には面のきれいさ（風向）が波高と同じくらい重要なため
    オフショアとオンショアの差を大きめに取る。
    実体験を踏まえ、風速0〜3m/sを適度、4m/sをやや強い、
    5m/s以上は風向に関わらずサーフィン不可として評価を大きく下げる。
    """
    d = direction % 360
    if d <= 45 or d >= 315:
        dir_score, dir_name = 100, "オフショア"
    elif (45 < d <= 90) or (270 <= d < 315):
        dir_score, dir_name = 65,  "サイドオフショア"
    elif (90 < d <= 135) or (225 <= d < 270):
        dir_score, dir_name = 30,  "サイドオンショア"
    else:
        dir_score, dir_name = 10,  "オンショア"

    if speed >= 5:
        return 0, f"{dir_name}・強すぎる（風が強くサーフィン不可）"

    if speed <= 3:
        spd_score, spd_name = 100, "適度"
    else:
        spd_score, spd_name = 60,  "やや強め"

    combined = int(spd_score * 0.50 + dir_score * 0.50)

    if combined >= 90:
        quality = "風の条件は良好。乗れる波があるかは別途確認"
    elif combined >= 70:
        quality = "風の条件は比較的良好"
    else:
        quality = "やや面が乱れる"

    wind_label = f"{dir_name}・{spd_name}（{quality}）"
    return combined, wind_label


def _score_crowd(dt_date: date_type) -> tuple[int, str]:
    """
    日付から混雑スコアと混雑ラベルを返す
    土・日・祝日 → 20点（混雑）
    それ以外     → 100点（空いている）
    """
    is_weekend = dt_date.weekday() >= 5          # 土(5)・日(6)
    is_holiday = jpholiday.is_holiday(dt_date)   # 日本の祝日

    if is_weekend or is_holiday:
        if dt_date.weekday() == 5:
            label = "土曜（混雑）"
        elif dt_date.weekday() == 6:
            label = "日曜（混雑）"
        else:
            label = "祝日（混雑）"
        return 20, label
    else:
        return 100, "平日（空いている）"


def _score_weather(cloud_cover: float, precipitation: float) -> int:
    """
    雲量(%)・降水量(mm/h) から天気スコアを返す
    forecast.py の weather_desc 判定と同じ基準に揃えている
    雨（weather_desc="雨"）は 0点。
    """
    if precipitation >= 3.0:   return 0    # 雨
    elif precipitation >= 0.5: return 25   # 小雨
    elif precipitation >= 0.1: return 50   # にわか雨
    elif cloud_cover < 20:     return 100  # 快晴
    elif cloud_cover < 50:     return 90   # 晴れ
    elif cloud_cover < 80:     return 75   # 晴れ〜曇り
    else:                      return 60   # 曇り


# ---------- 総合スコア ----------

def _score_tide(at: datetime | None, height: float,
                tides: dict | None) -> tuple[int, str]:
    """満干潮間を余弦補間した相対潮位による個人向け暫定評価。"""
    if at is None or not tides:
        return 50, "未判定・暫定50点（潮汐データ不足）"
    events = sorted([(dt, "high") for dt, _ in tides.get("highs", [])]
                    + [(dt, "low") for dt, _ in tides.get("lows", [])])
    level = None
    falling = False
    phase = ""
    for dt, kind in events:
        if dt == at:
            level = 1.0 if kind == "high" else 0.0
            phase = "満潮" if kind == "high" else "干潮"
            break
    if level is None:
        for (start, kind), (end, next_kind) in zip(events, events[1:]):
            if start < at < end and kind != next_kind:
                progress = (at - start).total_seconds() / (end - start).total_seconds()
                falling = kind == "high"
                level = (1 + cos(pi * progress)) / 2
                if not falling:
                    level = 1 - level
                phase = "下げ潮" if falling else "上げ潮"
                break
    if level is None:
        return 50, "未判定・暫定50点（前後の満干潮データ不足）"
    if height <= 0.6:
        points = min(100, round(20 + 70 * (1 - level) + (10 if falling else 0)))
        rule = "小波は干潮寄り・下げ潮を高評価"
    else:
        points = round(40 + 60 * (1 - abs(2 * level - 1)))
        rule = "中間潮位を高評価"
    return points, f"{phase}・相対潮位{level * 100:.0f}%推定（{rule}・暫定基準）"

def calculate(wave_height: float, swell_period: float, wave_period: float,
              wind_speed: float, wind_direction: float,
              cloud_cover: float = 0.0, precipitation: float = 0.0,
              dt_date: date_type | None = None, *,
              at: datetime | None = None, tides: dict | None = None) -> SurfScore:
    """
    初級者（横にすべる練習中）× ミッドレングス7.8ft 向け総合サーフィン適性スコアを計算する

    重み: 波高40% + 風30% + 周期20% + 潮10%。
    混雑と天気は参考情報として保持し、総合点には含めない。
    「周期」の表示・採点はうねり本来の周期（swell_period）を使う。
    合成周期（wave_period）は swell_period との差分から海面の乱れ具合を
    判定するためだけに使う（_closeout_risk）。
    潮は満干潮から推定する。データ不足時は暫定50点。
    """
    wh_score,  wave_label  = _score_wave_height(wave_height)
    wp_score,  period_label = _score_wave_period(swell_period)
    wnd_score, wind_label  = _score_wind(wind_speed, wind_direction)
    wthr_score             = _score_weather(cloud_cover, precipitation)
    crd_score, crowd_label = _score_crowd(dt_date or date_type.today())
    tide_score, tide_label = _score_tide(at, wave_height, tides)

    risk_factor, risk_note = _closeout_risk(swell_period, wave_period, wave_height)
    wave_condition_score = round(
        (wh_score * 0.40 + wnd_score * 0.30 + wp_score * 0.20) * risk_factor
        + tide_score * 0.10
    )

    # 風・周期・潮の加点で、練習できる波の不足を相殺しない。
    # 2026/09/25の現地報告を踏まえた暫定基準（物理的な可否の断定ではない）。
    score_cap = 100
    if wave_height <= 0.35:
        score_cap = 39
        risk_note = "波が弱く、ショアブレイクのみの可能性。横に走れる波か現地確認を"
    elif wave_height <= 0.45:
        score_cap = 54
        risk_note = "小波のため練習できる波があるか要確認。" + risk_note
    elif wh_score == 0 or wnd_score == 0:
        score_cap = 39
        risk_note = "波高または風速が想定する練習条件の範囲外。" + risk_note
    wave_condition_score = min(wave_condition_score, score_cap)

    total = wave_condition_score

    # 好条件の日は上級ショートボーダーが集まり混雑しやすいため注意を促す
    # （実際の混雑状況はデータ化できないため、スコアではなく注意書きで表現する）
    crowd_caution = wave_condition_score >= 80

    # 点数だけでなく、クローズアウトリスクの有無も加味して行動判定にする。
    # 70点以上でもリスク注意書きがある場合は「行くべき」から外す
    # （見た目のスコアが良くても海面が乱れて練習にならなかった実績を踏まえた措置）。
    if total >= 70 and not risk_note:
        decision = "◎ 行くべき"
    elif total >= 55:
        decision = "△ 要注意（現地レポートも確認を）"
    else:
        decision = "✕ 見送り推奨"

    if total >= 85:
        rating, comment = "★★★★★", "絶好のコンディション！迷わず入ろう"
    elif total >= 70:
        rating, comment = "★★★★☆", "良いコンディション。ターン練習にもおすすめ"
    elif total >= 55:
        rating, comment = "★★★☆☆", "まずまず。練習にはなる"
    elif total >= 40:
        rating, comment = "★★☆☆☆", "やや難しいコンディション"
    elif total >= 25:
        rating, comment = "★☆☆☆☆", "初級者には厳しい。見学が無難"
    else:
        rating, comment = "☆☆☆☆☆", "サーフィン不向き（フラット or 波が大きすぎ）"

    return SurfScore(
        total=total,
        wave_condition_score=wave_condition_score,
        wave_score=wh_score,
        period_score=wp_score,
        period_label=period_label,
        wind_score=wnd_score,
        weather_score=wthr_score,
        crowd_score=crd_score,
        crowd_label=crowd_label,
        risk_note=risk_note,
        crowd_caution=crowd_caution,
        decision=decision,
        rating=rating,
        comment=comment,
        wave_label=wave_label,
        wind_label=wind_label,
        tide_score=tide_score,
        tide_label=tide_label,
    )


def best_windows(day_records: list[dict], tides: dict | None = None) -> list[dict]:
    """
    1日分のレコードを受け取り、サーフィン可能時間帯(5〜18時)のスコアを計算して返す
    """
    results = []
    for r in day_records:
        if not (5 <= r["datetime"].hour <= 18):
            continue
        score = calculate(
            r["wave_height"], r["swell_period"], r["wave_period"],
            r["wind_speed"],  r["wind_direction"],
            r["cloud_cover"], r["precipitation"],
            r["datetime"].date(),
            at=r["datetime"], tides=tides,
        )
        results.append({**r, "score": score})
    return results
