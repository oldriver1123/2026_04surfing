"""
notifier.py
LINE Messaging API またはメールでメッセージを送信する

LINE Notify は 2025年3月末に終了済み。
代替として LINE Messaging API（push message）を使用する。
セットアップ手順は setup_line.txt を参照。
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests


# ---------- LINE ----------

def send_line(channel_access_token: str, user_id: str, message: str) -> None:
    """
    LINE Messaging API の push message でテキスト送信

    Args:
        channel_access_token: LINE Developers > Messaging API > Channel access token
        user_id: 送信先の LINE User ID（Uxxxxxxxx...）
    """
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {channel_access_token}",
        "Content-Type": "application/json",
    }
    # LINE のテキストメッセージは1件あたり最大5000文字
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=15)
    if not resp.ok:
        raise RuntimeError(
            f"LINE送信失敗: {resp.status_code} {resp.text}"
        )


# ---------- Email ----------

def send_email(smtp_host: str, smtp_port: int,
               username: str, password: str,
               from_addr: str, to_addr: str,
               subject: str, body: str) -> None:
    """
    Gmail SMTP 送信（587番ポート STARTTLS を優先、失敗時は 465番 SSL にフォールバック）

    Gmail の場合:
      smtp_host = "smtp.gmail.com"
      smtp_port = 587  ← STARTTLS（推奨）
      password  = アプリパスワード（16桁、スペースなし）
    """
    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = msg.as_string()

    ctx = ssl.create_default_context()

    # PCのホスト名に無効文字が含まれる場合があるため固定名を使用
    SAFE_EHLO = "localhost"

    # 587番ポート (STARTTLS) で試みる
    try:
        with smtplib.SMTP(smtp_host, 587, timeout=20) as server:
            server.ehlo(SAFE_EHLO)
            server.starttls(context=ctx)
            server.ehlo(SAFE_EHLO)
            server.login(username, password)
            server.sendmail(from_addr, to_addr, raw)
        return
    except Exception as e_starttls:
        print(f"  [INFO] STARTTLS(587) 失敗、SSL(465) で再試行... ({e_starttls})")

    # 465番ポート (SSL) にフォールバック
    with smtplib.SMTP_SSL(smtp_host, 465, context=ctx, timeout=20) as server:
        server.ehlo(SAFE_EHLO)
        server.login(username, password)
        server.sendmail(from_addr, to_addr, raw)
