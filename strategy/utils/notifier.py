# ============================================================
# utils/notifier.py — 텔레그램 알림
# ============================================================

import requests
import logging
import os

logger = logging.getLogger(__name__)

# 환경변수에서 텔레그램 설정 로드 (기존 봇 설정 활용)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def send_message(text: str) -> bool:
    """
    텔레그램 메시지 전송
    Returns: True = 성공
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("텔레그램 설정 없음. 알림 스킵.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


def notify_entry(symbol: str, direction: str, entry_price: float,
                 sl_price: float, tp_price: float | None, leverage: int) -> None:
    tp_str = f"{tp_price:.4f}" if tp_price else "트레일링 스탑"
    text = (
        f"🟢 *포지션 진입*\n"
        f"종목: `{symbol}`\n"
        f"방향: `{direction}`\n"
        f"진입가: `{entry_price}`\n"
        f"손절가: `{sl_price:.4f}`\n"
        f"목표가: `{tp_str}`\n"
        f"레버리지: `{leverage}x`"
    )
    send_message(text)


def notify_close(symbol: str, close_type: str, close_price: float,
                 pnl_usdt: float, pnl_pct: float) -> None:
    emoji = "✅" if close_type == "TP" else "❌"
    text = (
        f"{emoji} *포지션 청산*\n"
        f"종목: `{symbol}`\n"
        f"유형: `{close_type}`\n"
        f"청산가: `{close_price}`\n"
        f"손익: `{pnl_usdt:+.2f} USDT ({pnl_pct:+.2%})`"
    )
    send_message(text)


def notify_daily_halt(stop_count: int) -> None:
    text = (
        f"⛔ *당일 매매 전면 중단*\n"
        f"누적 손절: `{stop_count}회`\n"
        f"내일 자정 자동 초기화됩니다."
    )
    send_message(text)


def notify_monthly_shutdown(drawdown: float) -> None:
    text = (
        f"🚨 *봇 전체 중단 — 월간 드로우다운 초과*\n"
        f"드로우다운: `{drawdown:.2%}`\n"
        f"한도: `15%`\n"
        f"수동으로 재시작이 필요합니다."
    )
    send_message(text)


def notify_bias_update(bias_dict: dict) -> None:
    lines = "\n".join([f"`{k}`: {v}" for k, v in bias_dict.items()])
    text = f"📊 *오늘의 바이어스 업데이트*\n{lines}"
    send_message(text)
