# ============================================================
# strategies/eth_strategy.py — 이더 전략 (신호기반)
# 슈퍼트렌드 ATR14 / 배수3.5 단독
# ============================================================
# 백테스트 검증: 슈퍼트렌드 단독 + 다음전환대기 청산 + 2배
# 보조지표 없음 (RSI/MACD 전부 제거)
#
# 이 파일은 "신호"만 반환한다.
# 진입/청산 타이밍(다음전환대기 등)은 bot.py가 포지션 상태로 판단.
# ============================================================

import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.indicators import calculate_supertrend, candles_to_dataframe

logger = logging.getLogger(__name__)

# 슈퍼트렌드 파라미터 (config와 일치)
ST_ATR_PERIOD = 14
ST_MULTIPLIER = 3.5

# 슈퍼트렌드 방향 정의 (indicators.py 실제 계산 기준)
#   supertrend_dir == -1 → 상승(LONG)
#   supertrend_dir == +1 → 하락(SHORT)
DIR_LONG = -1
DIR_SHORT = 1


def get_signal(candles: list) -> dict:
    """
    이더 슈퍼트렌드 신호 계산.

    Returns dict:
        {
            "direction": "LONG" / "SHORT",   # 현재 슈퍼트렌드 방향
            "flipped":   True / False,        # 직전 봉 대비 전환 발생 여부
            "flip_to":   "LONG"/"SHORT"/None, # 전환됐다면 어느 방향으로
            "price":     float,               # 최근 종가
        }
    데이터 부족 시 direction=None 반환.
    """
    if len(candles) < ST_ATR_PERIOD + 5:
        logger.warning("[ETH] 캔들 데이터 부족")
        return {"direction": None, "flipped": False, "flip_to": None, "price": 0.0}

    df = candles_to_dataframe(candles)
    st_df = calculate_supertrend(df, atr_period=ST_ATR_PERIOD, multiplier=ST_MULTIPLIER)

    cur_dir = int(st_df["supertrend_dir"].iloc[-1])
    prev_dir = int(st_df["supertrend_dir"].iloc[-2])
    price = float(df["close"].iloc[-1])

    direction = "LONG" if cur_dir == DIR_LONG else "SHORT"

    flipped = (cur_dir != prev_dir)
    flip_to = None
    if flipped:
        flip_to = "LONG" if cur_dir == DIR_LONG else "SHORT"
        logger.info(f"[ETH] 슈퍼트렌드 전환 → {flip_to} | 종가: {price}")

    return {
        "direction": direction,
        "flipped": flipped,
        "flip_to": flip_to,
        "price": price,
    }
