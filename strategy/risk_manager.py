# ============================================================
# risk_manager.py — 리스크 관리 (신호기반 전략용 · 단순화)
# ============================================================
# 이번 버전은 제한 없이 운영 (백테스트 재현 목적)
#   - 일일 손절 제한 없음
#   - 종목별 재진입 제한 없음
#   - ATR 손절/익절 없음 (신호기반 청산)
#   - 월간 드로우다운 제한 없음
# 포지션 크기 계산만 담당.
# ============================================================

import logging
from config import SYMBOLS

logger = logging.getLogger(__name__)


def calculate_position_size(symbol: str, total_balance: float) -> dict:
    """
    포지션 크기 계산.
    - 진입 증거금 = 총잔고 × 코인별 비중(capital_ratio)
    - 리플 25%, 이더 40%

    Returns:
        {
            "position_usdt": float,   # 진입 증거금 (USDT)
            "leverage": int,          # 레버리지
        }
    """
    cfg = SYMBOLS[symbol]
    ratio = cfg["capital_ratio"]
    leverage = cfg["max_leverage"]

    position_usdt = total_balance * ratio

    logger.info(
        f"[{symbol}] 포지션 계산 | 증거금: {position_usdt:.2f} USDT "
        f"({ratio*100:.0f}%) | 레버리지: {leverage}x"
    )

    return {
        "position_usdt": position_usdt,
        "leverage": leverage,
    }
