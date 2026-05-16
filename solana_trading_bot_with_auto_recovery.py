"""
Solana Trading Bot - 오류 수정 버전
로그 로테이션 + API 재연결 + 디스크 모니터링
"""

import logging
import logging.handlers
import os
import shutil
import signal
import sys
import time
import json
from datetime import datetime, timedelta
from functools import wraps
import traceback
import glob

import ccxt
import pandas as pd
import numpy as np
from binance.client import Client
from telegram import Bot
from telegram.error import TelegramError

# 설정 불러오기
try:
    from solana_bot_config import (
        BINANCE_API_KEY, 
        BINANCE_API_SECRET,
        SYMBOL,
        TIMEFRAME,
        LEVERAGE,
        INITIAL_CAPITAL,
        COMMISSION,
        PIVOT_LOOKBACK,
        RR_RATIO
    )
    from telegram_config import TELEGRAM_BOT_TOKEN, CHAT_ID
except ImportError as e:
    print(f"❌ 설정 파일 로드 실패: {e}")
    sys.exit(1)

# ============================================================
# 🔧 로깅 설정 (로그 로테이션 - 10MB마다 자동 정리)
# ============================================================

LOG_DIR = os.path.expanduser("~/solana_bot_new")
LOG_FILE = os.path.join(LOG_DIR, "sol_trading_bot.log")

os.makedirs(LOG_DIR, exist_ok=True)

# RotatingFileHandler: 10MB마다 자동으로 파일 교체
handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5  # 최대 5개 파일만 유지
)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info("=" * 80)
logger.info("🚀 Solana Trading Bot 시작 (로그 로테이션 활성화)")
logger.info("=" * 80)

# ============================================================
# 💾 디스크 모니터링 (90% 이상이면 경고 + 정리)
# ============================================================

def check_disk_space(threshold=90):
    """디스크 사용량 확인"""
    try:
        disk_usage = shutil.disk_usage("/")
        used_percent = (disk_usage.used / disk_usage.total) * 100
        free_gb = disk_usage.free / (1024 ** 3)
        
        status = "🟢 정상" if used_percent < threshold else "🔴 경고"
        logger.info(f"{status} | 디스크: {used_percent:.1f}% | 남은공간: {free_gb:.2f}GB")
        
        if used_percent > threshold:
            logger.warning(f"⚠️  디스크 부족! {used_percent:.1f}% 사용 중")
            return False
        
        return True
    except Exception as e:
        logger.error(f"❌ 디스크 체크 실패: {e}")
        return True

# ============================================================
# 🔄 API 재연결 (3회 자동 재시도)
# ============================================================

def retry_on_api_error(max_retries=3, delay=5):
    """API 오류 시 자동 재시도"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                    logger.warning(f"🔄 API 오류 (시도 {attempt+1}/{max_retries}): {type(e).__name__}")
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)
                        logger.info(f"⏳ {wait_time}초 후 재시도...")
                        time.sleep(wait_time)
                    else:
                        raise
                except Exception as e:
                    logger.error(f"❌ 오류: {type(e).__name__} - {e}")
                    raise
        return wrapper
    return decorator

# ============================================================
# 🔗 Binance 연결 (타임아웃 30초 + 재연결)
# ============================================================

@retry_on_api_error(max_retries=3, delay=5)
def connect_binance(api_key, api_secret):
    """Binance 연결"""
    try:
        logger.info("🔗 Binance Futures 연결 중...")
        
        exchange = ccxt.binance({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'timeout': 30000,  # 30초 타임아웃
            'options': {
                'defaultType': 'future',
                'warnOnFetchOpenOrdersWithoutSymbol': False,
            }
        })
        
        exchange.fetch_ticker(SYMBOL)
        logger.info(f"✅ Binance 연결 성공 ({SYMBOL})")
        return exchange
    
    except ccxt.AuthenticationError as e:
        logger.error(f"❌ API 인증 실패: {e}")
        raise
    except Exception as e:
        logger.error(f"❌ Binance 연결 실패: {e}")
        raise

# ============================================================
# 📱 텔레그램 알림
# ============================================================

def send_telegram_alert(message, bot_token=None, chat_id=None):
    """텔레그램 알림 (3회 재시도)"""
    if not bot_token or not chat_id:
        logger.warning("⚠️  텔레그램 설정 없음")
        return False
    
    for attempt in range(3):
        try:
            bot = Bot(token=bot_token)
            bot.send_message(chat_id=chat_id, text=message)
            logger.info(f"✅ 텔레그램 발송 성공")
            return True
        except TelegramError as e:
            logger.warning(f"🔄 텔레그램 실패 (시도 {attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(5)
        except Exception as e:
            logger.error(f"❌ 텔레그램 오류: {e}")
            break
    
    return False

# ============================================================
# 🛑 우아한 종료 처리
# ============================================================

class GracefulShutdown:
    """프로그램 종료 시 깔끔하게 정리"""
    def __init__(self):
        self.shutting_down = False
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, sig, frame):
        if self.shutting_down:
            logger.warning("⚠️  강제 종료 중...")
            sys.exit(1)
        
        logger.info("=" * 80)
        logger.info("🛑 봇 종료 신호 수신")
        logger.info("=" * 80)
        self.shutting_down = True
    
    def is_shutting_down(self):
        return self.shutting_down

# ============================================================
# 📊 매매 데이터 조회
# ============================================================

@retry_on_api_error(max_retries=2, delay=3)
def fetch_ohlcv_data(exchange, symbol, timeframe, limit=100):
    """캔들 데이터 조회"""
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        df = pd.DataFrame(
            ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('datetime', inplace=True)
        df = df.sort_index()
        
        logger.debug(f"✅ {symbol} 데이터 조회 완료 ({len(df)}개)")
        return df
    except Exception as e:
        logger.error(f"❌ 데이터 조회 실패: {e}")
        raise

def generate_signals(df, lookback=PIVOT_LOOKBACK):
    """거래 신호 생성"""
    try:
        df = df.copy()
        
        df['pivot'] = (df['high'].rolling(window=lookback).max() + 
                       df['low'].rolling(window=lookback).min()) / 2
        
        df['signal'] = np.where(df['close'] > df['pivot'], 1, 0)
        df['position'] = df['signal'].diff()
        
        return df
    except Exception as e:
        logger.error(f"❌ 신호 생성 실패: {e}")
        raise

# ============================================================
# 🎯 메인 루프
# ============================================================

def main():
    """메인 실행"""
    graceful_shutdown = GracefulShutdown()
    exchange = None
    
    logger.info("=" * 80)
    logger.info("🚀 Solana Trading Bot 시작")
    logger.info(f"📊 설정: {SYMBOL} | {TIMEFRAME} | 레버리지 {LEVERAGE}배")
    logger.info("=" * 80)
    
    try:
        # 디스크 초기 체크
        if not check_disk_space():
            logger.error("❌ 초기 디스크 부족 - 시작 실패")
            send_telegram_alert(
                "🚨 디스크 부족으로 봇이 시작되지 않았습니다.",
                TELEGRAM_BOT_TOKEN,
                CHAT_ID
            )
            return
        
        # Binance 연결
        exchange = connect_binance(BINANCE_API_KEY, BINANCE_API_SECRET)
        
        send_telegram_alert(
            f"✅ Solana 봇이 시작되었습니다.\n📊 {SYMBOL} | {TIMEFRAME}",
            TELEGRAM_BOT_TOKEN,
            CHAT_ID
        )
        
        # 메인 루프
        loop_count = 0
        last_disk_check = datetime.now()
        
        while not graceful_shutdown.is_shutting_down():
            try:
                loop_count += 1
                logger.debug(f"📍 루프 #{loop_count}")
                
                # 10분마다 디스크 체크
                if datetime.now() - last_disk_check > timedelta(minutes=10):
                    if not check_disk_space():
                        logger.error("❌ 디스크 부족 - 중지")
                        break
                    last_disk_check = datetime.now()
                
                # 데이터 조회
                df = fetch_ohlcv_data(exchange, SYMBOL, TIMEFRAME, limit=100)
                
                # 신호 생성
                df = generate_signals(df)
                
                # 거래 신호
                if 'position' in df.columns and df['position'].iloc[-1] != 0:
                    signal_type = "🟢 BUY" if df['position'].iloc[-1] == 1 else "🔴 SELL"
                    logger.info(f"{signal_type} | {SYMBOL} | {df['close'].iloc[-1]:.2f}")
                
                time.sleep(60)
            
            except KeyboardInterrupt:
                logger.info("⛔ 사용자 중단")
                break
            
            except Exception as e:
                logger.error(f"❌ 루프 오류: {type(e).__name__} - {e}")
                logger.debug(f"{traceback.format_exc()}")
                time.sleep(10)
        
    except Exception as e:
        logger.error(f"❌ 심각한 오류: {type(e).__name__} - {e}")
        logger.debug(f"{traceback.format_exc()}")
        
        send_telegram_alert(
            f"🚨 봇 오류:\n{type(e).__name__}: {str(e)[:100]}",
            TELEGRAM_BOT_TOKEN,
            CHAT_ID
        )
    
    finally:
        logger.info("=" * 80)
        logger.info("⛔ Solana Trading Bot 종료")
        logger.info("=" * 80)
        
        send_telegram_alert(
            "⛔ Solana 봇이 종료되었습니다.",
            TELEGRAM_BOT_TOKEN,
            CHAT_ID
        )

# ============================================================
# 🚀 실행
# ============================================================

if __name__ == "__main__":
    main()
