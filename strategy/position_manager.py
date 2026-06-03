# ============================================================
# position_manager.py — 포지션 상태 관리
# ============================================================

import logging
from datetime import datetime
import risk_manager

logger = logging.getLogger(__name__)

# 포지션 저장소
_positions: dict = {}


def has_position(symbol: str) -> bool:
    """
    해당 종목 현재 포지션 보유 여부
    Returns:
        True: 포지션 보유 중 → 시그널 무시
    """
    return symbol in _positions and _positions[symbol] is not None


def get_position(symbol: str) -> dict | None:
    """
    현재 포지션 정보 반환
    """
    return _positions.get(symbol, None)


def get_position_direction(symbol: str) -> str | None:
    """
    현재 포지션 방향 반환
    Returns:
        "LONG" / "SHORT" / None
    """
    pos = _positions.get(symbol)
    if pos:
        return pos.get("direction")
    return None


def open_position(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float | None,
    position_usdt: float,
    leverage: int,
) -> None:
    """
    포지션 오픈 기록
    direction: "LONG" / "SHORT"
    """
    _positions[symbol] = {
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "position_usdt": position_usdt,
        "leverage": leverage,
        "opened_at": datetime.utcnow().isoformat(),
        "highest_price": entry_price,   # 트레일링 스탑용 (SOL)
        "lowest_price": entry_price,    # 트레일링 스탑용 (SOL)
    }
    logger.info(
        f"[{symbol}] 포지션 오픈 | {direction} | "
        f"진입: {entry_price} | SL: {sl_price} | TP: {tp_price} | "
        f"증거금: {position_usdt} USDT | 레버리지: {leverage}x"
    )


def update_trailing_stop(symbol: str, current_price: float, trailing_distance: float) -> float | None:
    """
    트레일링 스탑 업데이트 (SOL 전용)
    current_price 기준으로 최고가/최저가 갱신
    Returns:
        새로운 손절가 or None (갱신 없음)
    """
    pos = _positions.get(symbol)
    if not pos:
        return None

    direction = pos["direction"]

    if direction == "LONG":
        if current_price > pos["highest_price"]:
            pos["highest_price"] = current_price
            new_sl = current_price - trailing_distance
            if new_sl > pos["sl_price"]:
                pos["sl_price"] = new_sl
                logger.info(f"[{symbol}] 트레일링 스탑 갱신: {new_sl:.4f}")
                return new_sl

    elif direction == "SHORT":
        if current_price < pos["lowest_price"]:
            pos["lowest_price"] = current_price
            new_sl = current_price + trailing_distance
            if new_sl < pos["sl_price"]:
                pos["sl_price"] = new_sl
                logger.info(f"[{symbol}] 트레일링 스탑 갱신: {new_sl:.4f}")
                return new_sl

    return None


def close_position(symbol: str, close_type: str, close_price: float) -> dict | None:
    """
    포지션 청산 기록
    close_type: "TP" (익절) / "SL" (손절) / "TRAILING" (트레일링 스탑)
    Returns:
        청산된 포지션 정보
    """
    pos = _positions.pop(symbol, None)
    if not pos:
        logger.warning(f"[{symbol}] 청산할 포지션 없음.")
        return None

    closed_at = datetime.utcnow().isoformat()

    # 손익 계산
    if pos["direction"] == "LONG":
        pnl_pct = (close_price - pos["entry_price"]) / pos["entry_price"]
    else:
        pnl_pct = (pos["entry_price"] - close_price) / pos["entry_price"]

    pnl_usdt = pos["position_usdt"] * pos["leverage"] * pnl_pct

    logger.info(
        f"[{symbol}] 포지션 청산 | {close_type} | "
        f"청산가: {close_price} | PnL: {pnl_usdt:.2f} USDT ({pnl_pct:.2%}) | "
        f"시각: {closed_at}"
    )

    # 손절 처리
    if close_type in ("SL", "TRAILING"):
        risk_manager.add_stop_loss(symbol)
        logger.warning(f"[{symbol}] 손절 처리 완료. 당일 재진입 금지.")

    return {
        **pos,
        "close_price": close_price,
        "close_type": close_type,
        "closed_at": closed_at,
        "pnl_usdt": pnl_usdt,
        "pnl_pct": pnl_pct,
    }


def get_all_positions() -> dict:
    """
    전체 포지션 현황 반환 (모니터링용)
    """
    return dict(_positions)


def reset_positions() -> None:
    """
    자정 리셋 (비상용 — 일반적으로 청산 후 자동 비워짐)
    """
    _positions.clear()
    logger.info("포지션 상태 초기화 완료")
