# ============================================================
# strategies/btc_strategy.py — BTC 전략
# 슈퍼트렌드 방향 + EMA 22 + 거래량 이동평균
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
    슈퍼트렌드 방향 + EMA 22 방향 + 거래량 확인
    """
    if len(candles) < 30:
        logger.warning("[BTC] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 10, 배수 3.0)
    st_df = calculate_supertrend(df, atr_period=10, multiplier=3.0)
    st_dir = st_df["supertrend_dir"].iloc[-1]  # -1=상승(롱), 1=하락(숏)

    # EMA 22
    ema22 = calculate_ema(df, period=22)
    current_close = df["close"].iloc[-1]
    current_ema22 = ema22.iloc[-1]

    # 거래량 이동평균
    vol_ma = calculate_volume_ma(df, period=20)
    current_volume = df["volume"].iloc[-1]
    current_vol_ma = vol_ma.iloc[-1]
    # 거래량 조건 완화: 평균의 80% 이상이면 통과
    volume_ok = current_volume > current_vol_ma * 0.8

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 상승 (-1)
    # 조건2: 현재가 > EMA 22
    # 조건3: 거래량 > 거래량 MA
    # 보조: 펀딩비 과열 아닐 것

    if (st_dir == -1
            and current_close > current_ema22
            and volume_ok
            and funding_rate <= FUNDING["long_limit"]):
        logger.info(
            f"[BTC] 롱 시그널 | 슈퍼트렌드 상승 | "
            f"현재가: {current_close:.2f} | EMA22: {current_ema22:.2f} | "
            f"펀딩비: {funding_rate:.4f}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 하락 (1)
    # 조건2: 현재가 < EMA 22
    # 조건3: 거래량 > 거래량 MA
    # 보조: 펀딩비 과열 아닐 것

    if (st_dir == 1
            and current_close < current_ema22
            and volume_ok
            and funding_rate >= FUNDING["short_limit"]):
        logger.info(
            f"[BTC] 숏 시그널 | 슈퍼트렌드 하락 | "
            f"현재가: {current_close:.2f} | EMA22: {current_ema22:.2f} | "
            f"펀딩비: {funding_rate:.4f}"
        )
        return "SHORT"

    return None


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
