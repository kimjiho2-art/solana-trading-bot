# ============================================================
# strategies/sol_strategy.py — SOL 전략
# 슈퍼트렌드 + RSI + 트레일링 스탑
# ============================================================

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import (
    calculate_atr,
    calculate_supertrend,
    calculate_rsi,
    candles_to_dataframe,
)
from config import INDICATORS, SYMBOLS

logger = logging.getLogger(__name__)


def check_signal(candles: list) -> str | None:
    """
    SOL 1시간봉 시그널 계산
    슈퍼트렌드 전환 + RSI 확인 (기준 완화)

    Args:
        candles: SOL 1시간봉 캔들 (최소 25개)

    Returns:
        "LONG" / "SHORT" / None
    """
    if len(candles) < 25:
        logger.warning("[SOL] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 7, 배수 2.0)
    st_df = calculate_supertrend(df, atr_period=7, multiplier=2.0)
    cross = st_df["supertrend_cross"].iloc[-1]

    # 슈퍼트렌드 전환 없으면 시그널 없음
    if cross not in ("BUY", "SELL"):
        return None

    # RSI (SOL은 기준 완화 — 빠른 진입)
    rsi = calculate_rsi(df, period=INDICATORS["rsi_period"])
    current_close = df["close"].iloc[-1]

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 BUY 전환
    # 조건2: RSI ≥ 45 (기준 완화)

    if cross == "BUY" and rsi >= 45:
        logger.info(
            f"[SOL] 롱 시그널 | 슈퍼트렌드 BUY | "
            f"RSI: {rsi:.2f} | 현재가: {current_close:.4f}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 SELL 전환
    # 조건2: RSI ≤ 55 (기준 완화)

    if cross == "SELL" and rsi <= 55:
        logger.info(
            f"[SOL] 숏 시그널 | 슈퍼트렌드 SELL | "
            f"RSI: {rsi:.2f} | 현재가: {current_close:.4f}"
        )
        return "SHORT"

    return None


def get_trailing_distance(candles: list) -> float:
    """
    트레일링 스탑 거리 반환
    ATR × trailing_atr_multiplier
    """
    df = candles_to_dataframe(candles)
    atr = calculate_atr(df, period=INDICATORS["atr_period"])
    multiplier = SYMBOLS["SOL"]["trailing_atr_multiplier"]
    return atr * multiplier


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
