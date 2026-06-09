# ============================================================
# strategies/xrp_strategy.py — XRP 전략
# 슈퍼트렌드 방향 + 볼린저밴드 위치 + 거래량 120%
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
    슈퍼트렌드 방향 + 볼린저밴드 중심선 + 거래량 120% 이상
    """
    if len(candles) < 30:
        logger.warning("[XRP] 캔들 데이터 부족")
        return None

    df = candles_to_dataframe(candles)

    # 슈퍼트렌드 계산 (ATR 7, 배수 2.0)
    st_df = calculate_supertrend(df, atr_period=7, multiplier=2.0)
    st_dir = st_df["supertrend_dir"].iloc[-1]  # -1=상승, 1=하락

    # 볼린저밴드
    upper, middle, lower = calculate_bollinger_bands(
        df,
        period=INDICATORS["bb_period"],
        std_dev=INDICATORS["bb_std"],
    )
    current_close = df["close"].iloc[-1]
    current_middle = middle.iloc[-1]

    # 거래량 급증 (150% → 120%로 완화)
    volume_surge = calculate_volume_surge(df, ratio=1.2)

    # ── 롱 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 상승 (-1)
    # 조건2: 현재가 ≥ 볼린저밴드 중심선
    # 조건3: 거래량 ≥ 평균 대비 120%

    if st_dir == -1 and current_close >= current_middle and volume_surge:
        logger.info(
            f"[XRP] 롱 시그널 | 슈퍼트렌드 상승 | "
            f"현재가: {current_close:.4f} | BB중심: {current_middle:.4f}"
        )
        return "LONG"

    # ── 숏 시그널 ──────────────────────────────────────────
    # 조건1: 슈퍼트렌드 방향 = 하락 (1)
    # 조건2: 현재가 ≤ 볼린저밴드 중심선
    # 조건3: 거래량 ≥ 평균 대비 120%

    if st_dir == 1 and current_close <= current_middle and volume_surge:
        logger.info(
            f"[XRP] 숏 시그널 | 슈퍼트렌드 하락 | "
            f"현재가: {current_close:.4f} | BB중심: {current_middle:.4f}"
        )
        return "SHORT"

    return None


def get_current_atr(candles: list) -> float:
    df = candles_to_dataframe(candles)
    return calculate_atr(df, period=INDICATORS["atr_period"])
