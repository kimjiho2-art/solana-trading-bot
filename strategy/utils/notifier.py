# ============================================================
# utils/notifier.py — 텔레그램 상세 보고 시스템
# ============================================================

import requests
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

def _get_token():
    token = os.getenv("TELEGRAM_TOKEN", "")
    if not token:
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../config"))
            from telegram_config import TELEGRAM_BOT_TOKEN
            token = TELEGRAM_BOT_TOKEN
        except Exception:
            pass
    return token

def _get_chat_id():
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../config"))
            from telegram_config import TELEGRAM_CHAT_ID as CHAT_ID
            chat_id = str(CHAT_ID)
        except Exception:
            pass
    return chat_id

# 당일 손익 누적 추적
_daily_pnl = 0.0
_daily_trade_count = 0
_daily_win_count = 0
_daily_loss_count = 0


def _now_kst() -> str:
    """현재 시각 KST 문자열 반환"""
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")


def _date_kst() -> str:
    """현재 날짜 KST 문자열 반환"""
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d")


def send_message(text: str) -> bool:
    """텔레그램 메시지 전송"""
    token = _get_token()
    chat_id = _get_chat_id()

    if not token or not chat_id:
        logger.warning("텔레그램 설정 없음. 알림 스킵.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,  
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


def reset_daily_stats() -> None:
    """자정 일일 통계 초기화"""
    global _daily_pnl, _daily_trade_count, _daily_win_count, _daily_loss_count
    _daily_pnl = 0.0
    _daily_trade_count = 0
    _daily_win_count = 0
    _daily_loss_count = 0


def _update_daily_stats(pnl_usdt: float, is_win: bool) -> None:
    """일일 통계 업데이트"""
    global _daily_pnl, _daily_trade_count, _daily_win_count, _daily_loss_count
    _daily_pnl += pnl_usdt
    _daily_trade_count += 1
    if is_win:
        _daily_win_count += 1
    else:
        _daily_loss_count += 1


# ============================================================
# 진입/청산 보고
# ============================================================

def notify_entry(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float | None,
    leverage: int,
    position_usdt: float,
    signal_info: dict = None,
    daily_bias: str = None,
) -> None:
    """포지션 진입 알림"""
    direction_emoji = "🟢" if direction == "LONG" else "🔴"
    direction_kr = "롱" if direction == "LONG" else "숏"

    sl_pct = abs(sl_price - entry_price) / entry_price * 100
    sl_sign = "-" if direction == "LONG" else "+"

    if tp_price:
        tp_pct = abs(tp_price - entry_price) / entry_price * 100
        tp_sign = "+" if direction == "LONG" else "-"
        tp_str = f"${tp_price:,.4f} ({tp_sign}{tp_pct:.2f}%)"
    else:
        tp_str = "트레일링 스탑"

    # 시그널 근거
    signal_text = ""
    if signal_info:
        signal_text = "\n\n📊 *시그널 근거*\n"
        for key, value in signal_info.items():
            signal_text += f"{key}: {value}\n"

    # 전일 바이어스
    bias_emoji = {"LONG": "🟢 양봉", "SHORT": "🔴 음봉", "NONE": "⚪ 도지"}.get(daily_bias, "")
    bias_text = f"\n전일 일봉: {bias_emoji}" if bias_emoji else ""

    text = (
        f"{direction_emoji} *[{symbol}] {direction_kr} 진입*\n"
        f"─────────────────\n"
        f"진입가:   `${entry_price:,.4f}`\n"
        f"손절가:   `${sl_price:,.4f} ({sl_sign}{sl_pct:.2f}%)`\n"
        f"목표가:   `{tp_str}`\n"
        f"레버리지: `{leverage}x`\n"
        f"증거금:   `{position_usdt:,.0f} USDT`"
        f"{signal_text}"
        f"{bias_text}\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


def notify_close_tp(
    symbol: str,
    direction: str,
    entry_price: float,
    close_price: float,
    pnl_usdt: float,
    pnl_pct: float,
    hold_minutes: int,
) -> None:
    """익절 청산 알림"""
    _update_daily_stats(pnl_usdt, is_win=True)

    hold_h = hold_minutes // 60
    hold_m = hold_minutes % 60
    hold_str = f"{hold_h}시간 {hold_m}분" if hold_h > 0 else f"{hold_m}분"

    daily_pnl_sign = "+" if _daily_pnl >= 0 else ""

    text = (
        f"✅ *[{symbol}] 익절 청산*\n"
        f"─────────────────\n"
        f"진입가:   `${entry_price:,.4f}`\n"
        f"청산가:   `${close_price:,.4f}`\n"
        f"수익:     `+{pnl_usdt:,.0f} USDT (+{pnl_pct:.2f}%)`\n"
        f"보유시간: `{hold_str}`\n\n"
        f"💰 오늘 누적 손익: `{daily_pnl_sign}{_daily_pnl:,.0f} USDT`\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


def notify_close_sl(
    symbol: str,
    direction: str,
    entry_price: float,
    close_price: float,
    pnl_usdt: float,
    pnl_pct: float,
    hold_minutes: int,
    daily_stop_count: int,
    daily_stop_limit: int,
) -> None:
    """손절 청산 알림"""
    _update_daily_stats(pnl_usdt, is_win=False)

    hold_h = hold_minutes // 60
    hold_m = hold_minutes % 60
    hold_str = f"{hold_h}시간 {hold_m}분" if hold_h > 0 else f"{hold_m}분"

    daily_pnl_sign = "+" if _daily_pnl >= 0 else ""

    text = (
        f"❌ *[{symbol}] 손절 청산*\n"
        f"─────────────────\n"
        f"진입가:   `${entry_price:,.4f}`\n"
        f"청산가:   `${close_price:,.4f}`\n"
        f"손실:     `{pnl_usdt:,.0f} USDT ({pnl_pct:.2f}%)`\n"
        f"보유시간: `{hold_str}`\n\n"
        f"⚠️ 오늘 손절: `{daily_stop_count}/{daily_stop_limit}회`\n"
        f"💰 오늘 누적 손익: `{daily_pnl_sign}{_daily_pnl:,.0f} USDT`\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


# ============================================================
# 리스크 보고
# ============================================================

def notify_daily_halt(stop_count: int, current_balance: float) -> None:
    """일일 손절 2회 전면 중단 알림"""
    daily_pnl_sign = "+" if _daily_pnl >= 0 else ""

    text = (
        f"⛔ *당일 매매 전면 중단*\n"
        f"─────────────────\n"
        f"누적 손절: `{stop_count}회`\n"
        f"중단 시각: `{_now_kst()}`\n"
        f"오늘 손익: `{daily_pnl_sign}{_daily_pnl:,.0f} USDT`\n"
        f"현재 잔고: `{current_balance:,.0f} USDT`\n\n"
        f"내일 자정 자동 초기화됩니다."
    )
    send_message(text)


def notify_monthly_shutdown(drawdown: float, current_balance: float, start_balance: float) -> None:
    """월간 드로우다운 초과 봇 중단 알림"""
    text = (
        f"🚨 *봇 전체 중단 — 월간 드로우다운 초과*\n"
        f"─────────────────\n"
        f"월초 잔고:   `{start_balance:,.0f} USDT`\n"
        f"현재 잔고:   `{current_balance:,.0f} USDT`\n"
        f"드로우다운: `{drawdown:.2%}`\n"
        f"한도:        `15%`\n\n"
        f"⚠️ 수동으로 재시작이 필요합니다.\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


# ============================================================
# 일일 현황 보고
# ============================================================

def notify_bias_update(
    bias_dict: dict,
    prev_pnl: float = 0.0,
    prev_trade_count: int = 0,
    prev_win_count: int = 0,
    prev_loss_count: int = 0,
    current_balance: float = 0.0,
) -> None:
    """매일 아침 바이어스 + 전일 결산 보고"""
    bias_lines = ""
    for coin, bias in bias_dict.items():
        if bias == "LONG":
            bias_lines += f"  {coin}:  🟢 롱만 허용 (전일 양봉)\n"
        elif bias == "SHORT":
            bias_lines += f"  {coin}:  🔴 숏만 허용 (전일 음봉)\n"
        else:
            bias_lines += f"  {coin}:  ⚪ 거래 제한 (도지)\n"

    prev_pnl_sign = "+" if prev_pnl >= 0 else ""

    text = (
        f"📊 *오늘의 바이어스* ({_date_kst()})\n"
        f"─────────────────────────────\n"
        f"{bias_lines}\n"
        f"*전일 결산*\n"
        f"매매:  `{prev_trade_count}회 (익절 {prev_win_count} / 손절 {prev_loss_count})`\n"
        f"손익:  `{prev_pnl_sign}{prev_pnl:,.0f} USDT`\n"
        f"잔고:  `{current_balance:,.0f} USDT`"
    )
    send_message(text)


def notify_daily_summary(current_balance: float) -> None:
    """매일 자정 당일 최종 결산 보고"""
    daily_pnl_sign = "+" if _daily_pnl >= 0 else ""
    result_emoji = "📈" if _daily_pnl >= 0 else "📉"

    text = (
        f"{result_emoji} *당일 최종 결산* ({_date_kst()})\n"
        f"─────────────────────────────\n"
        f"총 매매:  `{_daily_trade_count}회`\n"
        f"익절:     `{_daily_win_count}회`\n"
        f"손절:     `{_daily_loss_count}회`\n"
        f"당일 손익: `{daily_pnl_sign}{_daily_pnl:,.0f} USDT`\n"
        f"현재 잔고: `{current_balance:,.0f} USDT`\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


# ============================================================
# 무시된 시그널 보고
# ============================================================

def notify_signal_ignored(symbol: str, signal: str, reason: str) -> None:
    """시그널 무시 보고"""
    direction_kr = "롱" if signal == "LONG" else "숏"

    text = (
        f"ℹ️ *[{symbol}] 시그널 무시*\n"
        f"─────────────────\n"
        f"시그널: `{direction_kr}`\n"
        f"이유:   `{reason}`\n"
        f"🕐 {_now_kst()}"
    )
    send_message(text)


# ============================================================
# 봇 오류/중단 보고
# ============================================================

def notify_bot_error(error_type: str, error_msg: str, last_position: str = None) -> None:
    """봇 오류 발생 알림"""
    position_text = f"\n마지막 포지션: `{last_position}`" if last_position else ""

    text = (
        f"🚨 *봇 오류 발생*\n"
        f"─────────────────────────────\n"
        f"오류 종류: `{error_type}`\n"
        f"발생 시각: `{_now_kst()}`\n"
        f"오류 내용: `{error_msg}`"
        f"{position_text}\n\n"
        f"⚠️ 즉시 확인이 필요합니다."
    )
    send_message(text)


def notify_bot_shutdown(reason: str, last_position: str = None) -> None:
    """봇 강제 중단 알림"""
    position_text = f"\n마지막 포지션: `{last_position}`" if last_position else ""

    text = (
        f"🚨 *봇 강제 중단*\n"
        f"─────────────────────────────\n"
        f"원인:     `{reason}`\n"
        f"중단 시각: `{_now_kst()}`"
        f"{position_text}\n\n"
        f"⚠️ 즉시 확인이 필요합니다."
    )
    send_message(text)


def get_daily_stats() -> dict:
    """현재 일일 통계 반환"""
    return {
        "pnl": _daily_pnl,
        "trade_count": _daily_trade_count,
        "win_count": _daily_win_count,
        "loss_count": _daily_loss_count,
    }
