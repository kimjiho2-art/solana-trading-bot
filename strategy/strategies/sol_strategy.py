# ============================================================
# strategies/sol_strategy.py — SOL 전략
# 슈퍼트렌드 방향 + RSI + 트레일링 스탑
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
    슈퍼트렌드 방향 + RSI 확인 (기준 완화)

    변경: 전환 시점이 아닌 방향 일치 시 진입
    """
    if len(candles) < 25:
        logger.warning("[SOL] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 7, 배수 2.0)
    st_df = calculate_supertrend(df, atr_period=7, multiplier=2.0)
    st_dir = st_df["supertrend_dir"].iloc[-1]  # -1=상승, 1=하락

    # RSI (SOL은 기준 완화)
    rsi = calculate_rsi(df, period=INDICATORS["rsi_period"])
    current_close = df["close"].iloc[-1]

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 상승 (-1)
    # 조건2: RSI ≥ 45 (기준 완화)

    if st_dir == -1 and rsi >= 45:
        logger.info(
            f"[SOL] 롱 시그널 | 슈퍼트렌드 상승 | "
            f"RSI: {rsi:.2f} | 현재가: {current_close:.4f}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 하락 (1)
    # 조건2: RSI ≤ 55 (기준 완화)

    if st_dir == 1 and rsi <= 55:
        logger.info(
            f"[SOL] 숏 시그널 | 슈퍼트렌드 하락 | "
            f"RSI: {rsi:.2f} | 현재가: {current_close:.4f}"
        )
        return "SHORT"

    return None


def get_trailing_distance(candles: list) -> float:
    df = candles_to_dataframe(candles)
    atr = calculate_atr(df, period=INDICATORS["atr_period"])
    multiplier = SYMBOLS["SOL"]["trailing_atr_multiplier"]
    return atr * multiplier


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
