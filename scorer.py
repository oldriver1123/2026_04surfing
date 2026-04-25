"""
scorer.py
初心者向けサーフィン適性スコアリング

重み配分:
  波高  50%
  風    50%
  ※ 混雑・天気・周期はメール本文に表示のみ（スコアに含まない）

茅ヶ崎・鵠沼はともに南向きビーチ:
  - オフショア（良）: 北風  = 315〜45°
  - サイドオフ:       北東・北西 = 45〜90° / 270〜315°
  - サイドオン:       東・西    = 90〜135° / 225〜270°
  - オンショア（悪）: 南風  = 135〜225°
"""

from dataclasses import dataclass
from datetime import date as date_type

import jpholiday


@dataclass
class SurfScore:
    total: int          # 総合スコア (0-100)
    wave_score: int     # 波高スコア
    period_score: int   # 周期スコア（内訳表示用）
    wind_score: int     # 風スコア
    weather_score: int  # 天気スコア
    crowd_score: int    # 混雑スコア
    crowd_label: str    # 混雑度ラベル
    rating: str         # ★評価
    comment: str        # 一言コメント
    wave_label: str     # 波の大きさ説明
    wind_label: str     # 風の種類


# ---------- 個別スコア ----------

def _score_wave_height(h: float) -> tuple[int, str]:
    """波高スコアと説明（Open-Meteo は有義波高 Hs を返す）"""
    if h < 0.2:
        return 10,  "フラット（ほぼ波なし）"
    elif h < 0.4:
        return 55,  "ひざ以下（ホワイトウォーター練習向き）"
    elif h < 0.7:
        return 100, "ひざ〜腰（初心者に最適）"
    elif h < 1.0:
        return 85,  "腰〜胸（初心者にちょうど良い）"
    elif h < 1.4:
        return 60,  "胸〜肩（やや大きめ）"
    elif h < 2.0:
        return 25,  "肩〜頭（初心者には難しい）"
    else:
        return 5,   "頭オーバー（初心者には危険）"


def _score_wave_period(p: float) -> int:
    """波の周期スコア（長いほどクリーンな波になる）"""
    if p <= 0:   return 0
    elif p < 5:  return 20
    elif p < 7:  return 50
    elif p < 9:  return 80
    elif p <= 13: return 100
    elif p <= 16: return 75
    else:         return 50


def _score_wind(speed: float, direction: float) -> tuple[int, str]:
    """風速・風向スコアと種別ラベルを返す"""
    d = direction % 360
    if d <= 45 or d >= 315:
        dir_score, wind_label = 100, "オフショア（北風：理想的）"
    elif (45 < d <= 90) or (270 <= d < 315):
        dir_score, wind_label = 70,  "サイドオフショア"
    elif (90 < d <= 135) or (225 <= d < 270):
        dir_score, wind_label = 35,  "サイドオンショア"
    else:
        dir_score, wind_label = 10,  "オンショア（南風：波が乱れる）"

    if speed <= 2:   spd_score = 100
    elif speed <= 4: spd_score = 90
    elif speed <= 6: spd_score = 75
    elif speed <= 9: spd_score = 50
    elif speed <= 12: spd_score = 25
    else:            spd_score = 5

    return int(spd_score * 0.55 + dir_score * 0.45), wind_label


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
            label = f"祝日（混雑）"
        return 20, label
    else:
        return 100, "平日（空いている）"


def _score_weather(code: int) -> int:
    """
    WMO 天気コードから天気スコアを返す
    晴れ・薄曇りが高得点、雨・雷雨が低得点
    """
    if code <= 1:    return 100  # 快晴〜晴れ
    elif code <= 3:  return 85   # 曇り
    elif code <= 9:  return 60   # 霧・もや系
    elif code <= 19: return 50   # にわか雨（弱）
    elif code <= 39: return 30   # 雨・雪・吹雪
    elif code <= 49: return 55   # 霧
    elif code <= 59: return 45   # 霧雨
    elif code <= 69: return 30   # 雨
    elif code <= 79: return 20   # 雪
    elif code <= 84: return 35   # にわか雨
    else:            return 10   # 雷雨・激しい現象


# ---------- 総合スコア ----------

def calculate(wave_height: float, wave_period: float,
              wind_speed: float, wind_direction: float,
              weather_code: int = 0,
              dt_date: date_type | None = None) -> SurfScore:
    """
    初心者向け総合サーフィン適性スコアを計算する

    重み: 波高50% / 風50%
    混雑・天気・周期はスコアに含まず、表示情報として保持する
    """
    wh_score,  wave_label  = _score_wave_height(wave_height)
    wp_score               = _score_wave_period(wave_period)
    wnd_score, wind_label  = _score_wind(wind_speed, wind_direction)
    wthr_score             = _score_weather(weather_code)
    crd_score, crowd_label = _score_crowd(dt_date or date_type.today())

    total = round(
        wh_score  * 0.50 +
        wnd_score * 0.50
    )

    if total >= 85:
        rating, comment = "★★★★★", "絶好のコンディション！迷わず入ろう"
    elif total >= 70:
        rating, comment = "★★★★☆", "良いコンディション。初心者にもおすすめ"
    elif total >= 55:
        rating, comment = "★★★☆☆", "まずまず。練習にはなる"
    elif total >= 40:
        rating, comment = "★★☆☆☆", "やや難しいコンディション"
    elif total >= 25:
        rating, comment = "★☆☆☆☆", "初心者には厳しい。見学が無難"
    else:
        rating, comment = "☆☆☆☆☆", "サーフィン不向き（フラット or 波が大きすぎ）"

    return SurfScore(
        total=total,
        wave_score=wh_score,
        period_score=wp_score,
        wind_score=wnd_score,
        weather_score=wthr_score,
        crowd_score=crd_score,
        crowd_label=crowd_label,
        rating=rating,
        comment=comment,
        wave_label=wave_label,
        wind_label=wind_label,
    )


def best_windows(day_records: list[dict]) -> list[dict]:
    """
    1日分のレコードを受け取り、サーフィン可能時間帯(5〜18時)のスコアを計算して返す
    """
    results = []
    for r in day_records:
        if not (5 <= r["datetime"].hour <= 18):
            continue
        score = calculate(
            r["wave_height"], r["wave_period"],
            r["wind_speed"],  r["wind_direction"],
            int(r["weather_code"]),
            r["datetime"].date(),
        )
        results.append({**r, "score": score})
    return results
