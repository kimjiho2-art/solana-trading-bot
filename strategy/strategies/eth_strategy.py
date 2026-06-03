# ============================================================
# strategies/eth_strategy.py — ETH 전략
# 슈퍼트렌드 + RSI + MACD
# ============================================================

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import (
    calculate_atr,
    calculate_supertrend,
    calculate_rsi,
    calculate_macd,
    candles_to_dataframe,
)
from config import INDICATORS

logger = logging.getLogger(__name__)


def check_signal(
    eth_candles: list,
    btc_candles: list = None,
    btc_dominance_trend: str = "FLAT"
) -> str | None:
    """
    ETH 1시간봉 시그널 계산
    슈퍼트렌드 전환 + RSI 50 기준 + MACD 방향 일치

    Args:
        eth_candles: ETH 1시간봉 캔들 (최소 40개)
        btc_candles: 미사용 (호환성 유지)
        btc_dominance_trend: BTC 도미넌스 추세

    Returns:
        "LONG" / "SHORT" / None
    """
    if len(eth_candles) < 40:
        logger.warning("[ETH] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(eth_candles)

    # 슈퍼트렌드 계산 (ATR 10, 배수 3.0)
    st_df = calculate_supertrend(df, atr_period=10, multiplier=3.0)
    cross = st_df["supertrend_cross"].iloc[-1]

    # 슈퍼트렌드 전환 없으면 시그널 없음
    if cross not in ("BUY", "SELL"):
        return None

    # RSI
    rsi = calculate_rsi(df, period=INDICATORS["rsi_period"])

    # MACD 방향
    macd_line, signal_line, _ = calculate_macd(
        df,
        fast=INDICATORS["macd_fast"],
        slow=INDICATORS["macd_slow"],
        signal=INDICATORS["macd_signal"],
    )
    macd_up = macd_line.iloc[-1] > signal_line.iloc[-1]

    current_close = df["close"].iloc[-1]

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 BUY 전환
    # 조건2: RSI ≥ 50
    # 조건3: MACD 상승 방향

    if cross == "BUY" and rsi >= 50 and macd_up:
        logger.info(
            f"[ETH] 롱 시그널 | 슈퍼트렌드 BUY | "
            f"RSI: {rsi:.2f} | MACD 상승 | 현재가: {current_close}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 SELL 전환
    # 조건2: RSI ≤ 50
    # 조건3: MACD 하락 방향

    if cross == "SELL" and rsi <= 50 and not macd_up:
        logger.info(
            f"[ETH] 숏 시그널 | 슈퍼트렌드 SELL | "
            f"RSI: {rsi:.2f} | MACD 하락 | 현재가: {current_close}"
        )
        return "SHORT"

    return None


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
