# ============================================================
# position_manager.py — 포지션 상태 관리
# ============================================================

import logging
from datetime import datetime
import risk_manager

logger = logging.getLogger(__name__)

# 포지션 저장소
_positions: dict = {}

# ── SOL 단계별 트레일링 스탑 설정 ────────────────────────
# ROI 0~8%:    ATR × 2.0 (실시간 추적)
# ROI 8~10%:   ATR × 1.5 (실시간 추적)
# ROI 10~14%:  ATR × 1.0 (실시간 추적)
# ROI 14% 이상: 4% 단위로만 갱신 (직전 단계 수익 보장)
TRAILING_STEPS = [
    (0.14, 0.04),   # ROI 14% 이상: 4% 단위로 갱신
]
TRAILING_ATR_STAGES = [
    (0.10, 1.0),    # ROI 10% 이상: ATR × 1.0
    (0.08, 1.5),    # ROI 8% 이상:  ATR × 1.5
    (0.0,  2.0),    # ROI 0% 이상:  ATR × 2.0
]


def has_position(symbol: str) -> bool:
    return symbol in _positions and _positions[symbol] is not None


def get_position(symbol: str) -> dict | None:
    return _positions.get(symbol, None)


def get_position_direction(symbol: str) -> str | None:
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
    _positions[symbol] = {
        "direction": direction,
        "entry_price": entry_price,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "position_usdt": position_usdt,
        "leverage": leverage,
        "opened_at": datetime.utcnow().isoformat(),
        "highest_price": entry_price,
        "lowest_price": entry_price,
        "last_step_roi": 0.0,   # 마지막으로 갱신된 ROI 단계
    }
    logger.info(
        f"[{symbol}] 포지션 오픈 | {direction} | "
        f"진입: {entry_price} | SL: {sl_price} | TP: {tp_price} | "
        f"증거금: {position_usdt} USDT | 레버리지: {leverage}x"
    )


def _calculate_roi(pos: dict, current_price: float) -> float:
    """현재 ROI 계산 (레버리지 포함)"""
    entry = pos["entry_price"]
    leverage = pos["leverage"]
    if pos["direction"] == "LONG":
        return (current_price - entry) / entry * leverage
    else:
        return (entry - current_price) / entry * leverage


def _get_atr_multiplier(roi: float) -> float:
    """ROI 기준 ATR 배수 반환"""
    for threshold, multiplier in TRAILING_ATR_STAGES:
        if roi >= threshold:
            return multiplier
    return 2.0


def _get_guaranteed_price(pos: dict, step_roi: float) -> float:
    """
    직전 ROI 단계 보장 가격 계산 (B안)
    예: ROI 14% 도달 시 → ROI 10% 지점 가격으로 스탑 설정
    """
    entry = pos["entry_price"]
    leverage = pos["leverage"]
    prev_roi = step_roi - 0.04  # 직전 단계 ROI

    if prev_roi < 0:
        prev_roi = 0

    if pos["direction"] == "LONG":
        return entry * (1 + prev_roi / leverage)
    else:
        return entry * (1 - prev_roi / leverage)


def update_trailing_stop(symbol: str, current_price: float, atr: float) -> float | None:
    """
    단계별 트레일링 스탑 업데이트 (SOL 전용)

    ROI 0~8%:    ATR × 2.0 실시간 추적
    ROI 8~10%:   ATR × 1.5 실시간 추적
    ROI 10~14%:  ATR × 1.0 실시간 추적
    ROI 14% 이상: 4% 단위로 직전 단계 수익 보장

    Returns: 새로운 손절가 or None
    """
    pos = _positions.get(symbol)
    if not pos:
        return None

    direction = pos["direction"]
    roi = _calculate_roi(pos, current_price)

    # ── ROI 14% 이상: 4% 단위 갱신 (B안) ─────────────────
    if roi >= 0.14:
        # 현재 ROI가 속하는 4% 단위 스텝 계산
        # 예: ROI 14% → step 14%, ROI 17% → step 14%, ROI 18% → step 18%
        step = int(roi / 0.04) * 0.04
        step = round(step, 4)

        if step > pos["last_step_roi"]:
            # 새 단계 도달 → 직전 단계 수익 보장 가격으로 스탑 설정
            guaranteed_price = _get_guaranteed_price(pos, step)
            pos["last_step_roi"] = step

            if direction == "LONG":
                if guaranteed_price > pos["sl_price"]:
                    pos["sl_price"] = guaranteed_price
                    if current_price > pos["highest_price"]:
                        pos["highest_price"] = current_price
                    logger.info(
                        f"[{symbol}] 트레일링 스탑 갱신 (단계 ROI {step:.0%}) | "
                        f"스탑: {guaranteed_price:.4f}"
                    )
                    return guaranteed_price
            else:
                if guaranteed_price < pos["sl_price"]:
                    pos["sl_price"] = guaranteed_price
                    if current_price < pos["lowest_price"]:
                        pos["lowest_price"] = current_price
                    logger.info(
                        f"[{symbol}] 트레일링 스탑 갱신 (단계 ROI {step:.0%}) | "
                        f"스탑: {guaranteed_price:.4f}"
                    )
                    return guaranteed_price
        return None

    # ── ROI 0~14%: ATR 배수 실시간 추적 ──────────────────
    multiplier = _get_atr_multiplier(roi)
    trailing_distance = atr * multiplier

    if direction == "LONG":
        if current_price > pos["highest_price"]:
            pos["highest_price"] = current_price
            new_sl = current_price - trailing_distance
            if new_sl > pos["sl_price"]:
                pos["sl_price"] = new_sl
                logger.info(
                    f"[{symbol}] 트레일링 스탑 갱신 (ROI {roi:.1%} | ATR×{multiplier}) | "
                    f"스탑: {new_sl:.4f}"
                )
                return new_sl

    elif direction == "SHORT":
        if current_price < pos["lowest_price"]:
            pos["lowest_price"] = current_price
            new_sl = current_price + trailing_distance
            if new_sl < pos["sl_price"]:
                pos["sl_price"] = new_sl
                logger.info(
                    f"[{symbol}] 트레일링 스탑 갱신 (ROI {roi:.1%} | ATR×{multiplier}) | "
                    f"스탑: {new_sl:.4f}"
                )
                return new_sl

    return None


def close_position(symbol: str, close_type: str, close_price: float) -> dict | None:
    pos = _positions.pop(symbol, None)
    if not pos:
        logger.warning(f"[{symbol}] 청산할 포지션 없음.")
        return None

    closed_at = datetime.utcnow().isoformat()

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
    return dict(_positions)


def reset_positions() -> None:
    _positions.clear()
    logger.info("포지션 상태 초기화 완료")
