"""
ETH/USDT 선물 자동매매 봇
전략: EMA 크로스(8/21) + 추세 EMA(50) + RSI(50) + ATR×1.5 손절 + R:R 2.0 익절
실거래: 진입 주문 + STOP_MARKET 손절 + TAKE_PROFIT_MARKET 익절 모두 자동 실행
"""

import logging
import logging.handlers
import os
import shutil
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta
from functools import wraps

import ccxt
import numpy as np
import pandas as pd
from telegram import Bot
from telegram.error import TelegramError

from solana_bot_config import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    TIMEFRAME,
    COMMISSION,
)
from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID as CHAT_ID

SYMBOL          = 'ETH/USDT'
LEVERAGE        = 5
RISK_PER_TRADE  = 0.02

EMA_FAST        = 8
EMA_SLOW        = 25
EMA_TREND       = 50
RSI_PERIOD      = 14
RSI_THRESHOLD   = 50
ATR_PERIOD      = 14
ATR_MULTIPLIER  = 2.0
RR_RATIO        = 2.0

CHECK_INTERVAL  = 60

LOG_DIR  = os.path.expanduser("~/solana_bot_new")
LOG_FILE = os.path.join(LOG_DIR, "eth_trading_bot.log")
os.makedirs(LOG_DIR, exist_ok=True)

handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
)
fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
handler.setFormatter(fmt)

logger = logging.getLogger("eth_bot")
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())

def send_telegram(msg: str):
    import requests
    for attempt in range(3):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            resp = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
            if resp.status_code == 200:
                logger.info("✅ 텔레그램 발송")
                return True
            else:
                logger.warning(f"🔄 텔레그램 실패 {attempt+1}/3: {resp.text}")
        except Exception as e:
            logger.error(f"❌ 텔레그램 오류: {e}")
        time.sleep(5)
    return False

def retry(max_retries=3, delay=5):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                    logger.warning(f"🔄 API 재시도 {attempt+1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay * (2 ** attempt))
                    else:
                        raise
        return wrapper
    return decorator

@retry(max_retries=3, delay=5)
def connect_binance():
    logger.info("🔗 Binance Futures 연결 중...")
    exchange = ccxt.binance({
        'apiKey': BINANCE_API_KEY,
        'secret': BINANCE_SECRET_KEY,
        'enableRateLimit': True,
        'timeout': 30000,
        'options': {'defaultType': 'future'}
    })
    exchange.load_markets()
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
        logger.info(f"✅ 레버리지 {LEVERAGE}배 설정 완료")
    except Exception as e:
        logger.warning(f"⚠️ 레버리지 설정 실패: {e}")
    try:
        exchange.set_margin_mode('isolated', SYMBOL)
        logger.info("✅ 마진 모드: isolated 설정")
    except Exception as e:
        logger.warning(f"⚠️ 마진 모드 설정 실패: {e}")
    logger.info(f"✅ Binance 연결 성공 ({SYMBOL})")
    return exchange

@retry(max_retries=2, delay=3)
def fetch_ohlcv(exchange) -> pd.DataFrame:
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('datetime', inplace=True)
    return df.sort_index()

def calc_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema_fast']  = df['close'].ewm(span=EMA_FAST,  adjust=False).mean()
    df['ema_slow']  = df['close'].ewm(span=EMA_SLOW,  adjust=False).mean()
    df['ema_trend'] = df['close'].ewm(span=EMA_TREND, adjust=False).mean()
    delta = df['close'].diff()
    gain  = delta.clip(lower=0).rolling(RSI_PERIOD).mean()
    loss  = (-delta.clip(upper=0)).rolling(RSI_PERIOD).mean()
    rs    = gain / loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - df['close'].shift()).abs(),
        (df['low']  - df['close'].shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(ATR_PERIOD).mean()
    cross_long  = (df['ema_fast'].shift(1) <= df['ema_slow'].shift(1)) & \
                  (df['ema_fast'].shift(2) <= df['ema_slow'].shift(2))
    cross_short = (df['ema_fast'].shift(1) >= df['ema_slow'].shift(1)) & \
                  (df['ema_fast'].shift(2) >= df['ema_slow'].shift(2))
    trend_up   = df['close'] > df['ema_trend']
    trend_down = df['close'] < df['ema_trend']
    rsi_long   = df['rsi'] > RSI_THRESHOLD
    rsi_short  = df['rsi'] < RSI_THRESHOLD
    df['signal'] = 0
    df.loc[cross_long  & trend_up   & rsi_long,  'signal'] = 1
    df.loc[cross_short & trend_down & rsi_short, 'signal'] = -1
    return df

def get_position(exchange):
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            if float(p['contracts']) != 0:
                return p
    except Exception as e:
        logger.error(f"❌ 포지션 조회 실패: {e}")
    return None

def get_balance(exchange) -> float:
    try:
        bal = exchange.fetch_balance()
        return float(bal['USDT']['free'])
    except Exception as e:
        logger.error(f"❌ 잔고 조회 실패: {e}")
        return 0.0

def calc_qty(exchange, entry_price: float, atr: float) -> float:
    balance   = get_balance(exchange)
    risk_usdt = balance * RISK_PER_TRADE
    stop_dist = ATR_MULTIPLIER * atr
    qty       = risk_usdt / stop_dist
    market    = exchange.markets.get(SYMBOL, {})
    min_qty   = float(market.get('limits', {}).get('amount', {}).get('min', 0.001))
    qty       = max(qty, min_qty)
    qty       = float(exchange.amount_to_precision(SYMBOL, qty))
    logger.info(f"💰 잔고: ${balance:.2f} | 리스크: ${risk_usdt:.2f} | 손절폭: ${stop_dist:.2f} | 수량: {qty} ETH")
    return qty

def cancel_all_orders(exchange):
    try:
        exchange.cancel_all_orders(SYMBOL)
        logger.info("🗑️ 미체결 주문 전체 취소")
    except Exception as e:
        logger.warning(f"⚠️ 주문 취소 실패: {e}")

def close_position(exchange, position: dict):
    try:
        side      = position['side']
        contracts = abs(float(position['contracts']))
        close_side = 'sell' if side == 'long' else 'buy'
        exchange.create_market_order(SYMBOL, close_side, contracts, params={'reduceOnly': True})
        logger.info(f"✅ 포지션 청산: {side} {contracts} ETH")
        return True
    except Exception as e:
        logger.error(f"❌ 포지션 청산 실패: {e}")
        return False

def open_long(exchange, qty: float, entry_price: float, atr: float):
    sl_price = round(entry_price - ATR_MULTIPLIER * atr, 2)
    tp_price = round(entry_price + ATR_MULTIPLIER * atr * RR_RATIO, 2)
    try:
        exchange.create_market_order(SYMBOL, 'buy', qty)
        logger.info(f"✅ 롱 진입 | 수량: {qty} | 가격: ~${entry_price:.2f}")
        time.sleep(1)
        exchange.create_order(SYMBOL, 'STOP_MARKET', 'sell', qty, params={'stopPrice': sl_price, 'reduceOnly': True})
        logger.info(f"🛑 손절: ${sl_price:.2f}")
        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'sell', qty, params={'stopPrice': tp_price, 'reduceOnly': True})
        logger.info(f"🎯 익절: ${tp_price:.2f}")
        send_telegram(
            f"🟢 ETH 롱 진입\n"
            f"진입가: ${entry_price:.2f}\n"
            f"손절가: ${sl_price:.2f}  (-{((entry_price-sl_price)/entry_price*100):.2f}%)\n"
            f"익절가: ${tp_price:.2f}  (+{((tp_price-entry_price)/entry_price*100):.2f}%)\n"
            f"수량: {qty} ETH | 레버리지: {LEVERAGE}x"
        )
        return True
    except Exception as e:
        logger.error(f"❌ 롱 진입 실패: {e}\n{traceback.format_exc()}")
        send_telegram(f"🚨 롱 진입 실패\n{str(e)[:100]}")
        return False

def open_short(exchange, qty: float, entry_price: float, atr: float):
    sl_price = round(entry_price + ATR_MULTIPLIER * atr, 2)
    tp_price = round(entry_price - ATR_MULTIPLIER * atr * RR_RATIO, 2)
    try:
        exchange.create_market_order(SYMBOL, 'sell', qty)
        logger.info(f"✅ 숏 진입 | 수량: {qty} | 가격: ~${entry_price:.2f}")
        time.sleep(1)
        exchange.create_order(SYMBOL, 'STOP_MARKET', 'buy', qty, params={'stopPrice': sl_price, 'reduceOnly': True})
        logger.info(f"🛑 손절: ${sl_price:.2f}")
        exchange.create_order(SYMBOL, 'TAKE_PROFIT_MARKET', 'buy', qty, params={'stopPrice': tp_price, 'reduceOnly': True})
        logger.info(f"🎯 익절: ${tp_price:.2f}")
        send_telegram(
            f"🔴 ETH 숏 진입\n"
            f"진입가: ${entry_price:.2f}\n"
            f"손절가: ${sl_price:.2f}  (+{((sl_price-entry_price)/entry_price*100):.2f}%)\n"
            f"익절가: ${tp_price:.2f}  (-{((entry_price-tp_price)/entry_price*100):.2f}%)\n"
            f"수량: {qty} ETH | 레버리지: {LEVERAGE}x"
        )
        return True
    except Exception as e:
        logger.error(f"❌ 숏 진입 실패: {e}\n{traceback.format_exc()}")
        send_telegram(f"🚨 숏 진입 실패\n{str(e)[:100]}")
        return False

def check_position_closed(exchange, prev_position: dict) -> bool:
    current = get_position(exchange)
    if current is None:
        side  = prev_position.get('side', '?')
        entry = float(prev_position.get('entryPrice', 0))
        pnl   = float(prev_position.get('unrealizedPnl', 0))
        send_telegram(f"✅ ETH {side.upper()} 포지션 종료\n진입가: ${entry:.2f}\n손익: ${pnl:.2f}")
        logger.info(f"✅ 포지션 종료 | {side} | 손익: ${pnl:.2f}")
        return True
    return False

def check_disk_space(threshold=90) -> bool:
    try:
        usage = shutil.disk_usage("/")
        pct   = usage.used / usage.total * 100
        free  = usage.free / (1024 ** 3)
        logger.info(f"💾 디스크: {pct:.1f}% | 여유: {free:.2f}GB")
        if pct > threshold:
            logger.warning(f"⚠️ 디스크 부족! {pct:.1f}%")
            return False
        return True
    except Exception as e:
        logger.error(f"❌ 디스크 체크 실패: {e}")
        return True

class GracefulShutdown:
    def __init__(self):
        self.shutting_down = False
        signal.signal(signal.SIGTERM, self._handler)
        signal.signal(signal.SIGINT, self._handler)
    def _handler(self, sig, frame):
        logger.info("🛑 종료 신호 수신")
        self.shutting_down = True
    def is_shutting_down(self):
        return self.shutting_down

def main():
    shutdown    = GracefulShutdown()
    exchange    = None
    position    = None
    last_signal = 0
    last_disk   = datetime.now()

    logger.info("=" * 70)
    logger.info("🚀 ETH 자동매매 봇 시작")
    logger.info(f"📊 {SYMBOL} | {TIMEFRAME} | 레버리지 {LEVERAGE}배")
    logger.info(f"📐 EMA {EMA_FAST}/{EMA_SLOW}/{EMA_TREND} | RSI {RSI_THRESHOLD} | ATR×{ATR_MULTIPLIER} | R:R {RR_RATIO}")
    logger.info("=" * 70)

    try:
        if not check_disk_space():
            send_telegram("🚨 디스크 부족 — 봇 시작 실패")
            return

        exchange = connect_binance()

        send_telegram(
            f"✅ ETH 자동매매 봇 시작\n"
            f"종목: {SYMBOL} | {TIMEFRAME}\n"
            f"레버리지: {LEVERAGE}배\n"
            f"전략: EMA {EMA_FAST}/{EMA_SLOW}/{EMA_TREND} + RSI + ATR\n"
            f"손절: ATR×{ATR_MULTIPLIER} | 익절 R:R {RR_RATIO}"
        )

        loop = 0
        while not shutdown.is_shutting_down():
            loop += 1
            logger.debug(f"── 루프 #{loop} ──")

            if datetime.now() - last_disk > timedelta(minutes=10):
                check_disk_space()
                last_disk = datetime.now()

            try:
                df     = fetch_ohlcv(exchange)
                df     = calc_signals(df)
                latest = df.iloc[-2]
                signal = int(latest['signal'])
                price  = float(df.iloc[-1]['close'])
                atr    = float(latest['atr'])

                logger.debug(
                    f"현재가: ${price:.2f} | ATR: {atr:.2f} | "
                    f"EMA {latest['ema_fast']:.2f}/{latest['ema_slow']:.2f} | "
                    f"RSI: {latest['rsi']:.1f} | 신호: {signal}"
                )

                if position is not None:
                    if check_position_closed(exchange, position):
                        position    = None
                        last_signal = 0
                        cancel_all_orders(exchange)

                if signal != 0 and signal != last_signal:
                    if position is not None:
                        logger.info("🔄 반대 신호 — 기존 포지션 청산 후 재진입")
                        cancel_all_orders(exchange)
                        close_position(exchange, position)
                        position = None
                        time.sleep(2)

                    qty = calc_qty(exchange, price, atr)
                    if qty <= 0:
                        logger.warning("⚠️ 수량 계산 실패 — 진입 건너뜀")
                    else:
                        if signal == 1:
                            success = open_long(exchange, qty, price, atr)
                        else:
                            success = open_short(exchange, qty, price, atr)

                        if success:
                            time.sleep(2)
                            position    = get_position(exchange)
                            last_signal = signal

            except Exception as e:
                logger.error(f"❌ 루프 오류: {e}\n{traceback.format_exc()}")
                time.sleep(10)

            time.sleep(CHECK_INTERVAL)

    except Exception as e:
        logger.error(f"❌ 치명적 오류: {e}\n{traceback.format_exc()}")
        send_telegram(f"🚨 봇 치명적 오류\n{type(e).__name__}: {str(e)[:150]}")

    finally:
        logger.info("=" * 70)
        logger.info("⛔ ETH 자동매매 봇 종료")
        logger.info("=" * 70)
        send_telegram("⛔ ETH 자동매매 봇이 종료되었습니다.")

if __name__ == "__main__":
    main()
