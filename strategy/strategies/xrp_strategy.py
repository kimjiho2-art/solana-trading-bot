# ============================================================
# strategies/xrp_strategy.py — XRP 전략
# 슈퍼트렌드 + 볼린저밴드 돌파 + 거래량 급증
# ============================================================

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import (
    calculate_atr,
    calculate_supertrend,
    calculate_bollinger_bands,
    calculate_volume_surge,
    candles_to_dataframe,
)
from config import INDICATORS

logger = logging.getLogger(__name__)


def check_signal(candles: list) -> str | None:
    """
    XRP 1시간봉 시그널 계산
    슈퍼트렌드 전환 + 볼린저밴드 돌파 + 거래량 150% 급증

    Args:
        candles: XRP 1시간봉 캔들 (최소 30개)

    Returns:
        "LONG" / "SHORT" / None
    """
    if len(candles) < 30:
        logger.warning("[XRP] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 7, 배수 2.0)
    st_df = calculate_supertrend(df, atr_period=7, multiplier=2.0)
    cross = st_df["supertrend_cross"].iloc[-1]

    # 슈퍼트렌드 전환 없으면 시그널 없음
    if cross not in ("BUY", "SELL"):
        return None

    # 볼린저밴드
    upper, middle, lower = calculate_bollinger_bands(
        df,
        period=INDICATORS["bb_period"],
        std_dev=INDICATORS["bb_std"],
    )
    current_close = df["close"].iloc[-1]
    current_upper = upper.iloc[-1]
    current_lower = lower.iloc[-1]

    # 거래량 급증
    volume_surge = calculate_volume_surge(df, ratio=INDICATORS["volume_surge_ratio"])

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 BUY 전환
    # 조건2: 현재가 > 볼린저밴드 상단 돌파
    # 조건3: 거래량 급증

    if cross == "BUY" and current_close > current_upper and volume_surge:
        logger.info(
            f"[XRP] 롱 시그널 | 슈퍼트렌드 BUY | "
            f"현재가: {current_close:.4f} | BB상단: {current_upper:.4f} | "
            f"거래량 급증: {volume_surge}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 SELL 전환
    # 조건2: 현재가 < 볼린저밴드 하단 이탈
    # 조건3: 거래량 급증

    if cross == "SELL" and current_close < current_lower and volume_surge:
        logger.info(
            f"[XRP] 숏 시그널 | 슈퍼트렌드 SELL | "
            f"현재가: {current_close:.4f} | BB하단: {current_lower:.4f} | "
            f"거래량 급증: {volume_surge}"
        )
        return "SHORT"

    return None


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
