# ──────────────────────────────────────────────────
# 솔라나 자동 매매 봇 설정 파일
# ──────────────────────────────────────────────────
# ⚠️ BINANCE API 키 설정 (필수!)
BINANCE_API_KEY = "Q3DhadGnGbJ1oSA5COfr8dK31QOibIqvEqhKpLb8PODLoJunGQJqGmw1HYPWFHon"
BINANCE_SECRET_KEY = "q4rCWJB9u5fA8RpB9szgWixQOSqqHfG38eoJcrEvIBzu0nL4VhpRONxOdJ0icmtp"
# 거래 설정
SYMBOL = 'SOLUSDT'
TIMEFRAME = '1h'
INITIAL_BALANCE = 600
LEVERAGE = 5
COMMISSION = 0.0007
# 파라미터
PIVOT_LOOKBACK = 5
RR_RATIO = 8.0
RISK_PER_TRADE = 0.02
# 로깅
LOG_FILE = 'sol_trading_bot.log'
FEE = COMMISSION
