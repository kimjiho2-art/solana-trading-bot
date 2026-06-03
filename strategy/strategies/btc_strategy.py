# ============================================================
# strategies/btc_strategy.py — BTC 전략
# 슈퍼트렌드 + EMA 200 + 거래량 이동평균
# ============================================================

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import (
    calculate_atr,
    calculate_supertrend,
    calculate_ema,
    calculate_volume_ma,
    candles_to_dataframe,
)
from config import INDICATORS, FUNDING

logger = logging.getLogger(__name__)


def check_signal(candles: list, funding_rate: float = 0.0) -> str | None:
    """
    BTC 1시간봉 시그널 계산
    슈퍼트렌드 전환 + EMA 200 방향 + 거래량 확인

    Args:
        candles: 1시간봉 캔들 데이터 (최소 210개 권장 - EMA 200 계산)
        funding_rate: 현재 펀딩비

    Returns:
        "LONG" / "SHORT" / None
    """
    if len(candles) < 210:
        logger.warning("[BTC] 캔들 데이터 부족 (최소 210개 필요)")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 10, 배수 3.0)
    st_df = calculate_supertrend(df, atr_period=10, multiplier=3.0)
    cross = st_df["supertrend_cross"].iloc[-1]

    # 슈퍼트렌드 전환 없으면 시그널 없음
    if cross not in ("BUY", "SELL"):
        return None

    # EMA 200
    ema200 = calculate_ema(df, period=200)
    current_close = df["close"].iloc[-1]
    current_ema200 = ema200.iloc[-1]

    # 거래량 이동평균
    vol_ma = calculate_volume_ma(df, period=20)
    current_volume = df["volume"].iloc[-1]
    current_vol_ma = vol_ma.iloc[-1]
    volume_ok = current_volume > current_vol_ma

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 BUY 전환 (숏→롱)
    # 조건2: 현재가 > EMA 200
    # 조건3: 거래량 > 거래량 MA
    # 보조: 펀딩비 과열 아닐 것

    if (cross == "BUY"
            and current_close > current_ema200
            and volume_ok
            and funding_rate <= FUNDING["long_limit"]):
        logger.info(
            f"[BTC] 롱 시그널 | 슈퍼트렌드 BUY | "
            f"현재가: {current_close:.2f} | EMA200: {current_ema200:.2f} | "
            f"펀딩비: {funding_rate:.4f}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 SELL 전환 (롱→숏)
    # 조건2: 현재가 < EMA 200
    # 조건3: 거래량 > 거래량 MA
    # 보조: 펀딩비 과열 아닐 것

    if (cross == "SELL"
            and current_close < current_ema200
            and volume_ok
            and funding_rate >= FUNDING["short_limit"]):
        logger.info(
            f"[BTC] 숏 시그널 | 슈퍼트렌드 SELL | "
            f"현재가: {current_close:.2f} | EMA200: {current_ema200:.2f} | "
            f"펀딩비: {funding_rate:.4f}"
        )
        return "SHORT"

    return None


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
