# ──────────────────────────────────────────────────
# 솔라나 자동 매매 봇 설정 파일
# ──────────────────────────────────────────────────

# ⚠️ BINANCE API 키 설정 (필수!)
BINANCE_API_KEY = "Q3DhadGnGbJ1oSA5COfr8dK31QOibIqvEqhKpLb8PODLoJunGQJqGmw1HYPWFHon"          # 바이낸스 API 키 입력
BINANCE_SECRET_KEY = "q4rCWJB9u5fA8RpB9szgWixQOSqqHfG38eoJcrEvIBzu0nL4VhpRONxOdJ0icmtp"    # 바이낸스 시크릿 키 입력

# 거래 설정
SYMBOL = 'SOLUSDT'                # 거래 종목
TIMEFRAME = '1h'                  # 1시간봉
INITIAL_BALANCE = 600             # 초기 자본 ($)
LEVERAGE = 5                      # 레버리지 5배
FEE = 0.0007                      # 거래 수수료 (0.07%)

# 최적 파라미터 (백테스팅 결과)
PIVOT_LOOKBACK = 5               # 스윙 포인트 감지
RR_RATIO = 8.0                   # 손익비 (Risk-to-Reward)
RISK_PER_TRADE = 0.02            # 거래당 위험 비율 (2%)

# 로깅
LOG_FILE = 'sol_trading_bot.log'
