"""
scorer.py
初級者（横にすべる練習中）× ミッドレングス（7.8ft）向けサーフィン適性スコアリング

想定ユーザー像:
  - サーフィンレベル: 初級者（ホワイトウォーターは卒業し、横にすべる練習中）
  - ボード: ミッドレングス 7.8ft（ボリュームがあり波を掴みやすく安定感がある）

重み配分:
  波の状態（風35% / 周期30% / 波高35% の合成）  70%
  混雑                                          20%
  天気                                          10%
  ※ 潮は満干潮の時刻・潮位としてメール本文に表示のみ（スコアには含まない）

鵠沼（スケートパーク前）は南向きビーチ:
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
    rating: str                # ★評価
    comment: str                # 一言コメント
    wave_label: str             # 波の大きさ説明
    wind_label: str             # 風の種類


# ---------- 個別スコア ----------

def _score_wave_height(h: float) -> tuple[int, str]:
    """
    波高スコアと説明（有義波高 Hs）
    横にすべる練習には「腰前後」が最も乗りやすく練習になるサイズ。
    それより大きくなると初級者には乗れない・危険なサイズとして急激に評価を下げる。
    実際に腰〜胸（0.8〜1.0m）でも急に崩れて練習にならなかった実績を踏まえ、
    このゾーンより上は上級者向けとして厳しめに採点する。
    """
    if h < 0.2:
        return 10,  "フラット（ほぼ波なし・練習不可）"
    elif h < 0.4:
        return 40,  "ひざ以下（推進力が弱くターン練習には物足りない）"
    elif h < 0.6:
        return 80,  "ひざ〜腰（もう少しで理想サイズ）"
    elif h < 0.8:
        return 100, "腰前後（ミッドレングスが一番活きるベストサイズ）"
    elif h < 1.0:
        return 40,  "腰〜胸（急に崩れやすく上級者向き。練習には大きすぎる可能性大）"
    elif h < 1.3:
        return 15,  "胸〜肩（初級者には大きすぎて練習にならない）"
    elif h < 1.8:
        return 5,   "肩〜頭（大きすぎて乗るのが難しい・危険）"
    else:
        return 0,   "頭オーバー（高すぎて乗れない・危険）"


def _score_wave_period(p: float) -> tuple[int, str]:
    """
    波の周期スコアと説明
    ミッドレングスは短周期の波でも掴みやすいが、面がきれいに整うのは
    やはり周期が長い groundswell。9〜13秒を最も高評価とする。
    """
    if p <= 0:
        return 0,   "データなし"
    elif p < 5:
        return 25,  "短め（面が乱れやすい）"
    elif p < 7:
        return 60,  "やや短め"
    elif p < 9:
        return 85,  "まずまず"
    elif p <= 13:
        return 100, "理想的（面がきれいで走りやすい）"
    elif p <= 16:
        return 80,  "ロングピリオド（パワフル）"
    else:
        return 55,  "非常に長い（威力が強くタイミング注意）"


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
    """
    d = direction % 360
    if d <= 45 or d >= 315:
        dir_score, wind_label = 100, "オフショア（理想的。面がきれいでターン練習に最適）"
    elif (45 < d <= 90) or (270 <= d < 315):
        dir_score, wind_label = 65,  "サイドオフショア（やや面が乱れるが練習可）"
    elif (90 < d <= 135) or (225 <= d < 270):
        dir_score, wind_label = 30,  "サイドオンショア（面が荒れやすい）"
    else:
        dir_score, wind_label = 10,  "オンショア（面が乱れターン練習には不向き）"

    if speed <= 2:    spd_score = 100
    elif speed <= 4:  spd_score = 88
    elif speed <= 6:  spd_score = 70
    elif speed <= 9:  spd_score = 45
    elif speed <= 12: spd_score = 20
    else:             spd_score = 5

    return int(spd_score * 0.50 + dir_score * 0.50), wind_label


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

def calculate(wave_height: float, swell_period: float, wave_period: float,
              wind_speed: float, wind_direction: float,
              cloud_cover: float = 0.0, precipitation: float = 0.0,
              dt_date: date_type | None = None) -> SurfScore:
    """
    初級者（横にすべる練習中）× ミッドレングス7.8ft 向け総合サーフィン適性スコアを計算する

    重み: 波の状態（風35% / 周期30% / 波高35%）70% → 混雑20% → 天気10%
    「周期」の表示・採点はうねり本来の周期（swell_period）を使う。
    合成周期（wave_period）は swell_period との差分から海面の乱れ具合を
    判定するためだけに使う（_closeout_risk）。
    潮はスコアに含まず、表示情報として保持する
    """
    wh_score,  wave_label  = _score_wave_height(wave_height)
    wp_score,  period_label = _score_wave_period(swell_period)
    wnd_score, wind_label  = _score_wind(wind_speed, wind_direction)
    wthr_score             = _score_weather(cloud_cover, precipitation)
    crd_score, crowd_label = _score_crowd(dt_date or date_type.today())

    wave_condition_score = round(
        wh_score  * 0.35 +
        wnd_score * 0.35 +
        wp_score  * 0.30
    )

    risk_factor, risk_note = _closeout_risk(swell_period, wave_period, wave_height)
    wave_condition_score = round(wave_condition_score * risk_factor)

    total = round(
        wave_condition_score * 0.70 +
        crd_score             * 0.20 +
        wthr_score             * 0.10
    )

    # 好条件の日は上級ショートボーダーが集まり混雑しやすいため注意を促す
    # （実際の混雑状況はデータ化できないため、スコアではなく注意書きで表現する）
    crowd_caution = wave_condition_score >= 80

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
            r["wave_height"], r["swell_period"], r["wave_period"],
            r["wind_speed"],  r["wind_direction"],
            r["cloud_cover"], r["precipitation"],
            r["datetime"].date(),
        )
        results.append({**r, "score": score})
    return results
