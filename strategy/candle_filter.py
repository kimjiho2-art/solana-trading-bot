# ============================================================
# candle_filter.py — 일봉 필터 (도지/양봉/음봉 판정)
# ============================================================

import logging
from config import RISK, SYMBOLS

logger = logging.getLogger(__name__)

# 당일 바이어스 저장소
_daily_bias: dict = {}


def is_doji(open_price: float, high: float, low: float, close: float) -> bool:
    """
    균형 도지 캔들 판정
    조건1: 몸통/전체범위 ≤ 15%
    조건2: 위꼬리/아래꼬리 비율 0.7 ~ 1.3 (균형)
    """
    total_range = high - low
    if total_range == 0:
        return True  # 이상 캔들은 도지로 처리

    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low

    body_ratio = body / total_range

    # 꼬리 균형 체크 (아래꼬리 0이면 한쪽 치우침 → 도지 아님)
    if lower_wick == 0:
        return False

    wick_ratio = upper_wick / lower_wick

    is_small_body = body_ratio <= RISK["doji_body_ratio"]
    is_balanced = RISK["doji_wick_ratio_min"] <= wick_ratio <= RISK["doji_wick_ratio_max"]

    return is_small_body and is_balanced


def get_candle_bias(open_price: float, high: float, low: float, close: float) -> str:
    """
    단일 캔들의 방향성 판정
    Returns:
        "LONG"  : 양봉 → 당일 롱만 허용
        "SHORT" : 음봉 → 당일 숏만 허용
        "NONE"  : 균형 도지 → 당일 거래 제한
    """
    if is_doji(open_price, high, low, close):
        return "NONE"
    elif close > open_price:
        return "LONG"
    else:
        return "SHORT"


def update_daily_bias(symbol: str, daily_candles: list) -> str:
    """
    전일 일봉 데이터를 받아 당일 바이어스 업데이트
    daily_candles: [open, high, low, close, volume] 형태의 리스트
                   가장 최근 완성된 일봉 = daily_candles[-2] (어제 봉)
    Returns:
        "LONG" / "SHORT" / "NONE"
    """
    if len(daily_candles) < 2:
        logger.warning(f"[{symbol}] 일봉 데이터 부족. 거래 제한.")
        _daily_bias[symbol] = "NONE"
        return "NONE"

    # 전일 완성 봉 (인덱스 -2: 마지막은 현재 진행 중인 봉)
    prev_candle = daily_candles[-2]
    o, h, l, c = prev_candle[1], prev_candle[2], prev_candle[3], prev_candle[4]

    bias = get_candle_bias(o, h, l, c)
    _daily_bias[symbol] = bias

    logger.info(f"[{symbol}] 전일 일봉 판정: {bias} (O:{o} H:{h} L:{l} C:{c})")
    return bias


def update_all_bias(fetch_daily_candles_func) -> dict:
    """
    4종목 전체 바이어스 업데이트
    매일 자정 호출
    fetch_daily_candles_func: symbol을 받아 일봉 캔들 리스트를 반환하는 함수
    Returns:
        {"BTC": "LONG", "ETH": "SHORT", "XRP": "NONE", "SOL": "LONG"}
    """
    result = {}
    for coin, cfg in SYMBOLS.items():
        try:
            candles = fetch_daily_candles_func(cfg["symbol"])
            bias = update_daily_bias(coin, candles)
            result[coin] = bias
        except Exception as e:
            logger.error(f"[{coin}] 일봉 바이어스 업데이트 실패: {e}")
            result[coin] = "NONE"  # 실패 시 안전하게 거래 제한

    logger.info(f"전체 바이어스 업데이트 완료: {result}")
    return result


def get_bias(symbol: str) -> str:
    """
    현재 저장된 종목 바이어스 반환
    """
    return _daily_bias.get(symbol, "NONE")


def reset_bias() -> None:
    """
    자정 리셋 시 바이어스 초기화
    """
    _daily_bias.clear()
    logger.info("전체 바이어스 초기화 완료")
