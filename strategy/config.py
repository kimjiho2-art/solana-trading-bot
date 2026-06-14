# ============================================================
# config.py — 설정값 중앙 관리 (리플·이더 신호기반 전략)
# ============================================================
# 백테스트 검증 전략:
#   XRP: 슈퍼트렌드 ATR10/3.0 + 1캔들지연 청산 + 4배 + 비중25%
#   ETH: 슈퍼트렌드 ATR14/3.5 + 다음전환대기 청산 + 2배 + 비중40%
# 청산: 신호기반 (슈퍼트렌드 방향 전환). ATR 손절/익절 없음
# ============================================================

# 종목별 설정
SYMBOLS = {
    "XRP": {
        "symbol": "XRPUSDT",
        "max_leverage": 4,             # 백테스트 최적 레버리지
        "capital_ratio": 0.25,         # 잔고의 25%
        "st_atr_period": 10,           # 슈퍼트렌드 ATR 기간
        "st_multiplier": 3.0,          # 슈퍼트렌드 배수
        "exit_mode": "delay1",         # 1캔들지연 청산
    },
    "ETH": {
        "symbol": "ETHUSDT",
        "max_leverage": 2,             # 백테스트 최적 레버리지
        "capital_ratio": 0.40,         # 잔고의 40%
        "st_atr_period": 14,           # 슈퍼트렌드 ATR 기간
        "st_multiplier": 3.5,          # 슈퍼트렌드 배수
        "exit_mode": "wait_next",      # 다음전환대기 청산
    },
}

# 시간 설정
TIMEFRAME = {
    "candle": "1h",                    # 기준 봉 (1시간봉)
    "reset_hour_utc": 0,               # 자정 리셋 (UTC)
}

# 슈퍼트렌드 방향 정의 (⚠️ 백테스트 기준)
#   direction == -1 : 상승 → 롱(LONG)
#   direction == +1 : 하락 → 숏(SHORT)
# indicators.py 의 calculate_supertrend 가 이 정의를 따르는지 반드시 확인
SUPERTREND_DIR = {
    "LONG": -1,
    "SHORT": 1,
}
