"""
forecast.py
Stormglass API を使って波・風・潮汐データを取得する

使用エンドポイント:
  Weather  : https://api.stormglass.io/v2/weather/point
  Tide     : https://api.stormglass.io/v2/tide/extremes/point

無料プラン: 1日10リクエストまで
  本アプリは2拠点 × (weather + tide) = 4リクエスト/日
"""

import requests
from collections import defaultdict
from datetime import datetime

import pytz

JST = pytz.timezone("Asia/Tokyo")

# 取得する気象パラメータ
WEATHER_PARAMS = ",".join([
    "waveHeight",
    "wavePeriod",
    "waveDirection",
    "swellHeight",
    "swellPeriod",
    "windSpeed",
    "windDirection",
    "airTemperature",
    "precipitation",
    "cloudCover",
])


def _pick(hour: dict, key: str) -> float:
    """
    Stormglass は各パラメータを複数ソース {noaa, icon, sg, ...} で返す。
    sg（Stormglass独自モデル）を優先し、なければ有効値の平均を返す。
    """
    sources = hour.get(key, {})
    if not sources:
        return 0.0
    if "sg" in sources and sources["sg"] is not None:
        return float(sources["sg"])
    vals = [float(v) for v in sources.values() if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _weather_desc(cloud_cover: float, precipitation: float) -> str:
    """雲量(%)・降水量(mm/h) から天気の説明を返す"""
    if precipitation >= 3.0:
        return "雨"
    elif precipitation >= 0.5:
        return "小雨"
    elif precipitation >= 0.1:
        return "にわか雨"
    elif cloud_cover < 20:
        return "快晴"
    elif cloud_cover < 50:
        return "晴れ"
    elif cloud_cover < 80:
        return "晴れ〜曇り"
    else:
        return "曇り"


def fetch_weather(lat: float, lon: float, api_key: str,
                  start_ts: int, end_ts: int) -> dict:
    """Stormglass Weather API から波・風・気温データを取得"""
    url = "https://api.stormglass.io/v2/weather/point"
    resp = requests.get(
        url,
        headers={"Authorization": api_key},
        params={"lat": lat, "lng": lon,
                "params": WEATHER_PARAMS,
                "start": start_ts, "end": end_ts},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_tides(lat: float, lon: float, api_key: str,
                start_ts: int, end_ts: int) -> dict:
    """Stormglass Tide Extremes API から満潮・干潮データを取得"""
    url = "https://api.stormglass.io/v2/tide/extremes/point"
    resp = requests.get(
        url,
        headers={"Authorization": api_key},
        params={"lat": lat, "lng": lon,
                "start": start_ts, "end": end_ts},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def build_hourly_records(weather_data: dict) -> list[dict]:
    """Stormglass weather レスポンスを時間ごとのレコードリストに変換（JST）"""
    records = []
    for hour in weather_data.get("hours", []):
        # UTC → JST に変換し tzinfo を除去
        dt = datetime.fromisoformat(hour["time"]) \
                     .astimezone(JST).replace(tzinfo=None)
        cloud  = _pick(hour, "cloudCover")
        precip = _pick(hour, "precipitation")
        records.append({
            "datetime":       dt,
            "wave_height":    _pick(hour, "waveHeight"),
            "wave_period":    _pick(hour, "wavePeriod"),
            "wave_direction": _pick(hour, "waveDirection"),
            "swell_height":   _pick(hour, "swellHeight"),
            "swell_period":   _pick(hour, "swellPeriod"),
            "wind_speed":     _pick(hour, "windSpeed"),
            "wind_direction": _pick(hour, "windDirection"),
            "temperature":    _pick(hour, "airTemperature"),
            "precipitation":  precip,
            "cloud_cover":    cloud,
            "weather_desc":   _weather_desc(cloud, precip),
            # scorer との互換性のためダミー値
            "weather_code":   0,
            "sea_level":      0.0,
        })
    return records


def compute_tides(tide_data: dict) -> dict[str, dict]:
    """
    Stormglass Tide Extremes レスポンスを日別の満潮・干潮辞書に変換

    Returns:
        { "YYYY-MM-DD": {"highs": [(datetime, height_m), ...],
                         "lows":  [(datetime, height_m), ...]} }
    """
    daily: dict = defaultdict(lambda: {"highs": [], "lows": []})
    for item in tide_data.get("data", []):
        dt  = datetime.fromisoformat(item["time"]) \
                      .astimezone(JST).replace(tzinfo=None)
        key = dt.strftime("%Y-%m-%d")
        h   = item["height"]
        if item["type"] == "high":
            daily[key]["highs"].append((dt, h))
        else:
            daily[key]["lows"].append((dt, h))
    return daily
