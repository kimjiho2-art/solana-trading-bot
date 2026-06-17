# ============================================================
# utils/indicators.py — 공통 지표 계산
# ============================================================

import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    ATR (Average True Range) 계산
    df 컬럼: high, low, close
    Returns: 최신 ATR 값
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()

    return float(atr.iloc[-1])


def calculate_ema(df: pd.DataFrame, period: int) -> pd.Series:
    """
    EMA (Exponential Moving Average) 계산
    Returns: EMA 시리즈
    """
    return df["close"].ewm(span=period, adjust=False).mean()


def calculate_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD 계산
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def calculate_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    볼린저밴드 계산
    Returns: (upper_band, middle_band, lower_band)
    """
    middle = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = middle + (std * std_dev)
    lower = middle - (std * std_dev)

    return upper, middle, lower


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """
    RSI (Relative Strength Index) 계산
    Returns: 최신 RSI 값
    """
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1])


def calculate_volume_surge(df: pd.DataFrame, ratio: float = 1.5) -> bool:
    """
    거래량 급증 감지
    현재 캔들 거래량이 이전 캔들들의 평균 대비 ratio 배 이상인지
    Returns: True = 거래량 급증
    """
    if len(df) < 2:
        return False

    current_volume = df["volume"].iloc[-1]
    avg_volume = df["volume"].iloc[:-1].mean()

    if avg_volume == 0:
        return False

    surge = current_volume / avg_volume
    return surge >= ratio


def calculate_supertrend(
    df: pd.DataFrame,
    atr_period: int = 10,
    multiplier: float = 3.0
) -> pd.DataFrame:
    """
    슈퍼트렌드 계산
    Returns: DataFrame with columns:
        supertrend       : 슈퍼트렌드 값
        supertrend_dir   : -1 = 상승(롱), 1 = 하락(숏)
                           ⚠️ config.py 의 SUPERTREND_DIR(LONG=-1, SHORT=1)과 동일.
                           (이 방향 정의를 절대 반대로 적지 말 것 — 과거 전부 SHORT 쏠림 원인)
        supertrend_cross : 'BUY' / 'SELL' / None (전환 시점)
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # ATR 계산
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / atr_period, adjust=False).mean()

    # 기본 상단/하단 밴드
    hl2 = (high + low) / 2
    upper_band = hl2 + (multiplier * atr)
    lower_band = hl2 - (multiplier * atr)

    # 슈퍼트렌드 계산
    supertrend = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(index=df.index, dtype=int)

    for i in range(1, len(df)):
        # 상단 밴드 조정
        if upper_band.iloc[i] < upper_band.iloc[i-1] or close.iloc[i-1] > upper_band.iloc[i-1]:
            final_upper = upper_band.iloc[i]
        else:
            final_upper = upper_band.iloc[i-1]

        # 하단 밴드 조정
        if lower_band.iloc[i] > lower_band.iloc[i-1] or close.iloc[i-1] < lower_band.iloc[i-1]:
            final_lower = lower_band.iloc[i]
        else:
            final_lower = lower_band.iloc[i-1]

        upper_band.iloc[i] = final_upper
        lower_band.iloc[i] = final_lower

        # 방향 결정
        if i == 1:
            direction.iloc[i] = 1
        elif supertrend.iloc[i-1] == upper_band.iloc[i-1]:
            direction.iloc[i] = -1 if close.iloc[i] > final_upper else 1
        else:
            direction.iloc[i] = 1 if close.iloc[i] < final_lower else -1

        supertrend.iloc[i] = final_lower if direction.iloc[i] == -1 else final_upper

    # 전환 시점 감지
    cross = pd.Series(index=df.index, dtype=object)
    for i in range(1, len(df)):
        if direction.iloc[i] == -1 and direction.iloc[i-1] == 1:
            cross.iloc[i] = "BUY"    # 숏→롱 전환
        elif direction.iloc[i] == 1 and direction.iloc[i-1] == -1:
            cross.iloc[i] = "SELL"   # 롱→숏 전환
        else:
            cross.iloc[i] = None

    result = df.copy()
    result["supertrend"] = supertrend
    result["supertrend_dir"] = direction
    result["supertrend_cross"] = cross

    return result


def calculate_volume_ma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """
    거래량 이동평균 계산 (BTC 전략용)
    Returns: 거래량 MA 시리즈
    """
    return df["volume"].rolling(window=period).mean()


def get_swing_high(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    직전 N캔들 최고가 (전고점) 반환 — SOL 전략용
    """
    return float(df["high"].iloc[-lookback:-1].max())


def get_swing_low(df: pd.DataFrame, lookback: int = 20) -> float:
    """
    직전 N캔들 최저가 (전저점) 반환 — SOL 전략용
    """
    return float(df["low"].iloc[-lookback:-1].min())


def candles_to_dataframe(candles: list) -> pd.DataFrame:
    """
    거래소 캔들 데이터를 DataFrame으로 변환
    candles: [[timestamp, open, high, low, close, volume], ...]
    """
    df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.astype({
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float,
    })
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df
