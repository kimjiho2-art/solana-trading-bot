# ============================================================
# config.py — 설정값 중앙 관리
# ============================================================

# 종목별 설정
SYMBOLS = {
    "BTC": {
        "symbol": "BTCUSDT",
        "max_leverage": 5,
        "capital_ratio": 0.25,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
        "trailing_stop": False,
    },
    "ETH": {
        "symbol": "ETHUSDT",
        "max_leverage": 5,
        "capital_ratio": 0.25,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
        "trailing_stop": False,
    },
    "XRP": {
        "symbol": "XRPUSDT",
        "max_leverage": 3,
        "capital_ratio": 0.25,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
        "trailing_stop": False,
    },
    "SOL": {
        "symbol": "SOLUSDT",
        "max_leverage": 3,
        "capital_ratio": 0.25,
        "atr_sl_multiplier": 1.5,
        "atr_tp_multiplier": None,       # SOL은 고정 목표가 없음
        "trailing_stop": True,
        "trailing_atr_multiplier": 2.0,
    },
}

# 리스크 관리 설정
RISK = {
    "daily_stop_limit": 2,               # 일일 손절 횟수 한도
    "monthly_drawdown_limit": 0.15,      # 월간 드로우다운 한도 15%
    "doji_body_ratio": 0.15,             # 도지 몸통 비율 기준
    "doji_wick_ratio_min": 0.7,          # 도지 꼬리 균형 최소
    "doji_wick_ratio_max": 1.3,          # 도지 꼬리 균형 최대
}

# 지표 설정
INDICATORS = {
    "atr_period": 14,
    "ema_fast": 20,
    "ema_slow": 50,
    "rsi_period": 14,
    "rsi_mid": 50,
    "bb_period": 20,
    "bb_std": 2,
    "volume_surge_ratio": 1.5,           # 거래량 급증 기준 150%
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "swing_lookback": 20,                # SOL 전고점/전저점 탐색 캔들 수
}

# 시간 설정
TIMEFRAME = {
    "candle": "1h",                      # 기준 봉
    "daily": "1d",                       # 일봉 필터
    "reset_hour_utc": 0,                 # 자정 리셋 (UTC)
}

# 펀딩비 설정 (BTC/ETH)
FUNDING = {
    "long_limit": 0.001,                 # +0.1% 초과 시 롱 제한
    "short_limit": -0.001,              # -0.1% 미만 시 숏 제한
}

# XRP 볼린저밴드 돌파 확인 캔들 수
XRP_BREAKOUT_CONFIRM_CANDLES = 3
