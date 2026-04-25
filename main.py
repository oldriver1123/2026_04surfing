"""
main.py
Build a surf forecast message and send it via LINE and/or email.
"""

import argparse
import io
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

import pytz

import forecast as fc
import scorer as sc
from notifier import send_email, send_line

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

JST = pytz.timezone("Asia/Tokyo")

LOCATIONS = [
    {
        "name": "茅ヶ崎（チーバー）",
        "lat": 35.320,
        "lon": 139.470,
    },
]

DAYS_TO_SHOW = 3


def load_config(path: str = "config.json") -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)


def group_by_day(records: list[dict]) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    for record in records:
        grouped[record["datetime"].strftime("%Y-%m-%d")].append(record)
    return grouped


def wind_dir_label(deg: float) -> str:
    dirs = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW",
    ]
    return dirs[round(deg / 22.5) % 16]


def day_label(target: date, today: date) -> str:
    diff = (target - today).days
    weekday = ["月", "火", "水", "木", "金", "土", "日"][target.weekday()]
    date_str = target.strftime("%m/%d")
    if diff == 1:
        return f"明日 {date_str}({weekday})"
    if diff == 2:
        return f"明後日 {date_str}({weekday})"
    if diff == 3:
        return f"3日後 {date_str}({weekday})"
    return f"{date_str}({weekday})"


def format_tides(tide_info: dict) -> tuple[str, str]:
    def fmt(entries: list[tuple[datetime, float]]) -> str:
        return "  ".join(f"{dt.strftime('%H:%M')}({height:+.2f}m)" for dt, height in entries)

    highs = fmt(tide_info.get("highs", [])) or "-"
    lows = fmt(tide_info.get("lows", [])) or "-"
    return highs, lows


def build_day_block(
    date_str: str,
    hours: list[dict],
    today: date,
    tide_info: dict | None = None,
) -> str:
    scored = sc.best_windows(hours)
    if not scored:
        return ""

    ranked = sorted(scored, key=lambda item: item["score"].total, reverse=True)
    best = ranked[0]
    score = best["score"]
    target = datetime.strptime(date_str, "%Y-%m-%d").date()
    best_hour = best["datetime"].hour
    end_hour = min(best_hour + 2, 20)

    window_records = [
        record for record in scored
        if best_hour <= record["datetime"].hour < end_hour
    ]
    avg_temp = (
        sum(record["temperature"] for record in window_records) / len(window_records)
        if window_records else best.get("temperature", 0.0)
    )

    lines = [
        f"■ {day_label(target, today)}",
        f"{score.rating} {score.total}点  {score.comment}",
        f"おすすめ {best_hour:02d}:00-{end_hour:02d}:00",
        f"波 {best['wave_height']:.1f}m / 周期 {best['wave_period']:.0f}s / 風 {wind_dir_label(best['wind_direction'])} {best['wind_speed']:.1f}m/s",
        f"天気 {best['weather_desc']} / 気温 {avg_temp:.0f}C / 混雑 {score.crowd_label}",
        f"波評価 {score.wave_label}",
        f"風評価 {score.wind_label}",
    ]

    if tide_info:
        highs, lows = format_tides(tide_info)
        lines.append(f"満潮 {highs}")
        lines.append(f"干潮 {lows}")

    return "\n".join(lines)


def build_location_section(
    location: dict,
    records: list[dict],
    tides_all: dict,
    today: date,
) -> str:
    daily = group_by_day(records)
    today_str = today.strftime("%Y-%m-%d")
    future_keys = [key for key in sorted(daily.keys()) if key > today_str][:DAYS_TO_SHOW]

    lines = [location["name"]]

    for date_str in future_keys:
        block = build_day_block(date_str, daily[date_str], today, tide_info=tides_all.get(date_str))
        if block:
            lines.append(block)

    return "\n".join(lines)


def build_full_message(location_sections: list[str]) -> str:
    valid_sections = [section for section in location_sections if section.strip()]
    if not valid_sections:
        return "今日はデータ取得できませんでした。時間をおいて再実行してください。"
    return "\n\n".join(valid_sections)


def send_notifications(message: str, cfg: dict, today: date) -> None:
    notification_cfg = cfg.get("notification", {})
    line_cfg = notification_cfg.get("line", {})
    email_cfg = notification_cfg.get("email", {})

    line_enabled = bool(line_cfg.get("enabled", False))
    email_enabled = bool(email_cfg.get("enabled", False))

    if not line_enabled and not email_enabled:
        print("[WARN] No notification channel is enabled.")
        print("       Set notification.line.enabled or notification.email.enabled in config.json.")
        return

    if line_enabled:
        channel_access_token = line_cfg.get("channel_access_token", "").strip()
        user_id = line_cfg.get("user_id", "").strip()
        if not channel_access_token or not user_id:
            print("[ERROR] LINE is enabled, but channel_access_token or user_id is empty.")
            sys.exit(1)

        print("Sending LINE notification...")
        try:
            send_line(
                channel_access_token=channel_access_token,
                user_id=user_id,
                message=message,
            )
            print("LINE notification sent.")
        except Exception as exc:
            print(f"[ERROR] Failed to send LINE notification: {exc}")
            sys.exit(1)

    if email_enabled:
        print("Sending email notification...")
        try:
            smtp = email_cfg["smtp"]
            send_email(
                smtp_host=smtp["host"],
                smtp_port=smtp["port"],
                username=smtp["username"],
                password=smtp["password"],
                from_addr=smtp["from"],
                to_addr=email_cfg["to"],
                subject=f"Surf forecast {today.strftime('%m/%d')}",
                body=message,
            )
            print(f"Email sent: {email_cfg['to']}")
        except Exception as exc:
            print(f"[ERROR] Failed to send email notification: {exc}")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and send a surf forecast notification.")
    parser.add_argument("--preview", action="store_true", help="Build the message only.")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    cfg = load_config(args.config)
    today = datetime.now(JST).date()

    api_key = cfg.get("stormglass_api_key", "").strip()
    if not api_key or api_key == "YOUR_STORMGLASS_API_KEY":
        print("[ERROR] stormglass_api_key is not configured in config.json.")
        sys.exit(1)

    start_dt = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    end_dt = start_dt + timedelta(days=3)
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    location_sections = []

    for location in LOCATIONS:
        print(f"Fetching data for {location['name']}...")
        try:
            weather_data = fc.fetch_weather(location["lat"], location["lon"], api_key, start_ts, end_ts)
            tide_data = fc.fetch_tides(location["lat"], location["lon"], api_key, start_ts, end_ts)
        except Exception as exc:
            print(f"[ERROR] Failed to fetch data for {location['name']}: {exc}")
            continue

        records = fc.build_hourly_records(weather_data)
        tides_all = fc.compute_tides(tide_data)
        section = build_location_section(location, records, tides_all, today)
        if section.strip():
            location_sections.append(section)

    message = build_full_message(location_sections)

    print("\n" + "=" * 55)
    print(message)
    print("=" * 55 + "\n")

    if args.preview:
        print("--preview mode: notifications were not sent.")
        return

    send_notifications(message, cfg, today)


if __name__ == "__main__":
    main()
