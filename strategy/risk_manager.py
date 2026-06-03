# ============================================================
# risk_manager.py — 리스크 관리
# ============================================================

import logging
from datetime import datetime
from config import RISK, SYMBOLS

logger = logging.getLogger(__name__)

# 상태 저장소
_state = {
    "daily_stop_count": 0,              # 당일 전 종목 합산 손절 횟수
    "stop_loss_symbols": set(),         # 당일 손절 발생 종목
    "trading_halted": False,            # 당일 전면 중단 여부
    "monthly_start_balance": None,      # 월초 잔고
    "bot_shutdown": False,              # 봇 전체 중단 (월간 드로우다운)
}


# ============================================================
# 일일 손절 관리
# ============================================================

def add_stop_loss(symbol: str) -> int:
    """
    손절 카운터 +1
    Returns: 현재 누적 손절 횟수
    """
    _state["daily_stop_count"] += 1
    _state["stop_loss_symbols"].add(symbol)

    count = _state["daily_stop_count"]
    logger.warning(f"[{symbol}] 손절 발생. 오늘 누적 손절: {count}회")

    if count >= RISK["daily_stop_limit"]:
        _state["trading_halted"] = True
        logger.warning("일일 손절 한도 도달. 당일 전 종목 매매 중단.")

    return count


def is_trading_allowed() -> bool:
    """
    당일 매매 가능 여부 확인
    Returns:
        False: 당일 손절 2회 이상 or 봇 전체 중단
    """
    if _state["bot_shutdown"]:
        logger.warning("봇 전체 중단 상태. 매매 불가.")
        return False
    if _state["trading_halted"]:
        logger.warning("당일 매매 중단 상태.")
        return False
    return True


def is_symbol_reentry_allowed(symbol: str) -> bool:
    """
    해당 종목 당일 재진입 가능 여부
    손절 이력 있으면 당일 재진입 금지
    Returns:
        False: 해당 종목 당일 손절 이력 있음
    """
    if symbol in _state["stop_loss_symbols"]:
        logger.info(f"[{symbol}] 당일 손절 이력 있음. 재진입 금지.")
        return False
    return True


# ============================================================
# 일일 리셋
# ============================================================

def reset_daily() -> None:
    """
    매일 자정 호출 — 일일 카운터 초기화
    """
    _state["daily_stop_count"] = 0
    _state["stop_loss_symbols"] = set()
    _state["trading_halted"] = False
    logger.info(f"[{datetime.utcnow().date()}] 일일 리스크 카운터 초기화 완료")


# ============================================================
# 월간 드로우다운 관리
# ============================================================

def set_monthly_start_balance(balance: float) -> None:
    """
    매월 초 잔고 기록
    """
    _state["monthly_start_balance"] = balance
    logger.info(f"월초 잔고 설정: {balance}")


def check_monthly_drawdown(current_balance: float) -> bool:
    """
    월간 드로우다운 체크
    Returns:
        True: 15% 초과 → 봇 전체 중단 필요
    """
    start = _state["monthly_start_balance"]
    if start is None or start == 0:
        return False

    drawdown = (start - current_balance) / start
    logger.info(f"월간 드로우다운: {drawdown:.2%} (한도: {RISK['monthly_drawdown_limit']:.2%})")

    if drawdown >= RISK["monthly_drawdown_limit"]:
        _state["bot_shutdown"] = True
        logger.critical(f"월간 드로우다운 {drawdown:.2%} 한도 초과. 봇 전체 중단.")
        return True

    return False


# ============================================================
# 포지션 사이즈 계산
# ============================================================

def calculate_position_size(
    symbol: str,
    entry_price: float,
    atr: float,
    total_balance: float
) -> dict:
    """
    ATR 기반 포지션 사이즈 계산
    - 종목당 최대 자본 25%
    - 손절폭 = ATR × 1.5
    - 포지션 사이즈 = (자본 × 25%) / 레버리지 적용
    Returns:
        {
            "position_usdt": float,     # 포지션 금액 (USDT)
            "leverage": int,            # 레버리지
            "sl_distance": float,       # 손절 거리 (USDT)
        }
    """
    cfg = SYMBOLS[symbol]
    max_capital = total_balance * cfg["capital_ratio"]
    sl_distance = atr * cfg["atr_sl_multiplier"]
    leverage = cfg["max_leverage"]

    # 실제 사용 증거금
    position_usdt = min(max_capital, max_capital)

    logger.info(
        f"[{symbol}] 포지션 계산 | 증거금: {position_usdt:.2f} USDT | "
        f"레버리지: {leverage}x | 손절거리: {sl_distance:.4f}"
    )

    return {
        "position_usdt": position_usdt,
        "leverage": leverage,
        "sl_distance": sl_distance,
    }


def calculate_sl_tp(
    symbol: str,
    entry_price: float,
    direction: str,
    atr: float
) -> dict:
    """
    손절가 / 목표가 계산
    direction: "LONG" / "SHORT"
    Returns:
        {
            "sl_price": float,
            "tp_price": float or None (SOL 트레일링)
        }
    """
    cfg = SYMBOLS[symbol]
    sl_dist = atr * cfg["atr_sl_multiplier"]

    if direction == "LONG":
        sl_price = entry_price - sl_dist
        tp_price = (
            entry_price + atr * cfg["atr_tp_multiplier"]
            if cfg["atr_tp_multiplier"] else None
        )
    else:  # SHORT
        sl_price = entry_price + sl_dist
        tp_price = (
            entry_price - atr * cfg["atr_tp_multiplier"]
            if cfg["atr_tp_multiplier"] else None
        )

    logger.info(
        f"[{symbol}] {direction} | 진입: {entry_price} | "
        f"손절: {sl_price:.4f} | 목표: {tp_price}"
    )

    return {"sl_price": sl_price, "tp_price": tp_price}


def get_state() -> dict:
    """
    현재 리스크 상태 반환 (모니터링용)
    """
    return {
        "daily_stop_count": _state["daily_stop_count"],
        "stop_loss_symbols": list(_state["stop_loss_symbols"]),
        "trading_halted": _state["trading_halted"],
        "bot_shutdown": _state["bot_shutdown"],
    }
