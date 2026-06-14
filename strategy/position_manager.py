# ============================================================
# position_manager.py — 포지션 상태 관리 (신호기반 전략용)
# ============================================================
# 트레일링 스탑 제거. 신호기반 청산 상태 추적.
#
# 청산 방식별 상태:
#   delay1(리플)    : 전환 감지 시 다음 신호처리에서 진입 (pending)
#   wait_next(이더) : 청산 후 바로 재진입 안 함. 다음 전환까지 대기 (armed)
#
# 중복진입 방지: has_position() 으로 보유중이면 진입 차단 (bot.py에서 확인)
# ============================================================

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 포지션 저장소: {coin: {...}}
_positions: dict = {}

# 청산방식 상태 저장소: {coin: {"pending": str|None, "armed": bool}}
#   pending: delay1 모드에서 다음 봉에 진입할 방향 ("LONG"/"SHORT"/None)
#   armed:   wait_next 모드에서 다음 전환 대기중 여부
_signal_state: dict = {}


# ── 포지션 조회 ──────────────────────────────────────────
def has_position(symbol: str) -> bool:
    return symbol in _positions and _positions[symbol] is not None


def get_position(symbol: str) -> dict | None:
    return _positions.get(symbol, None)


def get_position_direction(symbol: str) -> str | None:
    pos = _positions.get(symbol)
    return pos.get("direction") if pos else None


def get_all_positions() -> dict:
    return dict(_positions)


# ── 청산방식 상태 조회/설정 ──────────────────────────────
def _ensure_state(symbol: str) -> dict:
    if symbol not in _signal_state:
        _signal_state[symbol] = {"pending": None, "armed": False}
    return _signal_state[symbol]


def get_pending(symbol: str) -> str | None:
    return _ensure_state(symbol)["pending"]


def set_pending(symbol: str, direction: str | None) -> None:
    _ensure_state(symbol)["pending"] = direction


def is_armed(symbol: str) -> bool:
    return _ensure_state(symbol)["armed"]


def set_armed(symbol: str, value: bool) -> None:
    _ensure_state(symbol)["armed"] = value


# ── 포지션 열기/닫기 ─────────────────────────────────────
def open_position(
    symbol: str,
    direction: str,
    entry_price: float,
    position_usdt: float,
    leverage: int,
) -> None:
    _positions[symbol] = {
        "direction": direction,
        "entry_price": entry_price,
        "position_usdt": position_usdt,
        "leverage": leverage,
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        f"[{symbol}] 포지션 오픈 | {direction} | 진입: {entry_price} | "
        f"증거금: {position_usdt:.2f} USDT | 레버리지: {leverage}x"
    )


def close_position(symbol: str, close_price: float) -> dict | None:
    """
    포지션 청산. 손익 계산해서 반환.
    close_type 구분 없음 (신호기반 청산은 손익 부호로 TP/SL 판단)
    """
    pos = _positions.pop(symbol, None)
    if not pos:
        logger.warning(f"[{symbol}] 청산할 포지션 없음.")
        return None

    closed_at = datetime.now(timezone.utc).isoformat()

    if pos["direction"] == "LONG":
        pnl_pct = (close_price - pos["entry_price"]) / pos["entry_price"]
    else:
        pnl_pct = (pos["entry_price"] - close_price) / pos["entry_price"]

    pnl_usdt = pos["position_usdt"] * pos["leverage"] * pnl_pct

    logger.info(
        f"[{symbol}] 포지션 청산 | 청산가: {close_price} | "
        f"PnL: {pnl_usdt:.2f} USDT ({pnl_pct*100:.2f}%) | 시각: {closed_at}"
    )

    return {
        **pos,
        "close_price": close_price,
        "closed_at": closed_at,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": pnl_pct,
        "is_profit": pnl_usdt > 0,
    }


def reset_positions() -> None:
    _positions.clear()
    logger.info("포지션 상태 초기화 완료")
