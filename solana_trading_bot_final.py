# -*- coding: utf-8 -*-
"""
솔라나(SOL/USDT) 실시간 자동 매매 봇 + 텔레그램 알림 + 매매일지
거래소: Binance 선물 (Futures)
데이터: WebSocket 실시간 스트리밍
한글 완벽 지원
"""

import os
from datetime import datetime, timedelta
import time
import pandas as pd
import numpy as np
from binance.client import Client
from binance.exceptions import BinanceAPIException
import logging
import sys
import requests

# 설정 파일 import
from solana_bot_config import *
from telegram_config import *
from trading_journal import TradingJournal

# ──────────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────
# 매매일지 초기화
# ──────────────────────────────────────────────────

journal = TradingJournal('trading_journals')

# ──────────────────────────────────────────────────
# 텔레그램 알림 함수
# ──────────────────────────────────────────────────

def send_telegram_message(message):
    """텔레그램으로 메시지 전송"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, data=data)
        if response.status_code == 200:
            logger.info("📱 텔레그램 메시지 전송 완료")
        else:
            logger.warning(f"⚠️  텔레그램 전송 실패: {response.status_code}")
    except Exception as e:
        logger.error(f"❌ 텔레그램 전송 오류: {e}")

# ──────────────────────────────────────────────────
# Binance 클라이언트 초기화
# ──────────────────────────────────────────────────

def init_binance_client():
    """Binance API 클라이언트 초기화"""
    try:
        client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)
        # API 연결 테스트
        account = client.futures_account()
        logger.info(f"✅ Binance API 연결 성공")
        logger.info(f"   계정 잔고: ${account['totalWalletBalance']} USDT")
        
        # 텔레그램 알림
        msg = f"✅ <b>솔라나 자동 매매 봇 시작</b>\n\n"
        msg += f"🤖 봇 상태: 정상\n"
        msg += f"💰 계정 잔고: ${account['totalWalletBalance']} USDT\n"
        msg += f"⏰ 시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        send_telegram_message(msg)
        
        return client
    except BinanceAPIException as e:
        logger.error(f"❌ Binance API 오류: {e}")
        send_telegram_message(f"❌ <b>API 연결 실패</b>\n{str(e)}")
        raise
    except Exception as e:
        logger.error(f"❌ API 연결 실패: {e}")
        send_telegram_message(f"❌ <b>예상치 못한 오류</b>\n{str(e)}")
        raise

# ──────────────────────────────────────────────────
# 기술적 지표 계산
# ──────────────────────────────────────────────────

def calculate_swing_points(df, lookback=PIVOT_LOOKBACK):
    """스윙 하이/로우 계산"""
    df = df.copy()
    df['is_swing_high'] = df['high'] == df['high'].rolling(
        window=lookback*2+1, center=True
    ).max()
    df['is_swing_low'] = df['low'] == df['low'].rolling(
        window=lookback*2+1, center=True
    ).min()
    return df

def fetch_ohlcv(client, symbol, interval, limit=100):
    """OHLCV 데이터 조회"""
    try:
        klines = client.futures_klines(
            symbol=symbol,
            interval=interval,
            limit=limit
        )
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_av', 'trades', 'tb_base_av', 'tb_quote_av', 'ignore'
        ])
        
        # 데이터 타입 변환
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col])
        
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        
        return df[['open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        logger.error(f"❌ OHLCV 조회 실패: {e}")
        send_telegram_message(f"⚠️  <b>데이터 조회 실패</b>\n{str(e)}")
        return None

# ──────────────────────────────────────────────────
# 봇 클래스
# ──────────────────────────────────────────────────

class SolanaBot:
    def __init__(self, client, symbol, initial_balance, leverage):
        self.client = client
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.leverage = leverage
        self.current_balance = initial_balance
        self.in_position = False
        self.position_type = None
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.position_size = 0
        self.entry_time = None
        
        self.trades = []
        self.winning_trades = 0
        self.losing_trades = 0
        
        # 상태 변수
        self.current_trend = 0
        self.last_swing_high = 0
        self.last_swing_low = 0
        self.sweep_occurred = False
        self.sweep_timer = 0
        
        logger.info(f"🤖 봇 초기화 완료")
        logger.info(f"   종목: {symbol}")
        logger.info(f"   초기 자본: ${initial_balance}")
        logger.info(f"   레버리지: {leverage}배")
    
    def analyze_signal(self, df):
        """SMC 신호 분석"""
        if df is None or len(df) < PIVOT_LOOKBACK:
            return None, None
        
        df = calculate_swing_points(df, PIVOT_LOOKBACK)
        latest = df.iloc[-1]
        
        # 스윙 포인트 업데이트
        if latest['is_swing_high']:
            self.last_swing_high = latest['high']
        if latest['is_swing_low']:
            self.last_swing_low = latest['low']
        
        # 추세 식별
        if self.last_swing_high > 0 and latest['close'] > self.last_swing_high:
            self.current_trend = 1  # 상승 추세
        elif self.last_swing_low > 0 and latest['close'] < self.last_swing_low:
            self.current_trend = -1  # 하락 추세
        
        signal = None
        
        # 상승 추세 롱 신호
        if self.current_trend == 1 and not self.in_position:
            recent_lows = df['low'].iloc[-30:].loc[df['is_swing_low']]
            if not self.sweep_occurred and not recent_lows.empty:
                nearest_low = recent_lows.iloc[-1]
                if latest['low'] < nearest_low and latest['close'] > nearest_low:
                    self.sweep_occurred = True
                    self.stop_loss = latest['low'] * 0.999
                    self.sweep_timer = 0
            
            if self.sweep_occurred:
                self.sweep_timer += 1
                minor_high = df['high'].iloc[-5:].max()
                if latest['close'] > minor_high and self.sweep_timer <= 40:
                    signal = ('LONG', latest['close'])
        
        # 하락 추세 숏 신호
        elif self.current_trend == -1 and not self.in_position:
            recent_highs = df['high'].iloc[-30:].loc[df['is_swing_high']]
            if not self.sweep_occurred and not recent_highs.empty:
                nearest_high = recent_highs.iloc[-1]
                if latest['high'] > nearest_high and latest['close'] < nearest_high:
                    self.sweep_occurred = True
                    self.stop_loss = latest['high'] * 1.001
                    self.sweep_timer = 0
            
            if self.sweep_occurred:
                self.sweep_timer += 1
                minor_low = df['low'].iloc[-5:].min()
                if latest['close'] < minor_low and self.sweep_timer <= 40:
                    signal = ('SHORT', latest['close'])
        
        return signal, latest['close']
    
    def place_order(self, signal_type, entry_price):
        """주문 실행"""
        try:
            if signal_type == 'LONG':
                risk = entry_price - self.stop_loss
                if risk <= 0:
                    logger.warning(f"⚠️  롱 진입 실패: 위험 값 음수")
                    return False
                
                self.take_profit = entry_price + (risk * RR_RATIO)
                self.position_size = (self.current_balance * self.leverage) / entry_price
                
                # 선물 주문
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side='BUY',
                    type='MARKET',
                    quantity=round(self.position_size, 3),
                    leverage=self.leverage
                )
                
                logger.info(f"✅ 롱 진입")
                logger.info(f"   진입가: ${entry_price:.2f}")
                logger.info(f"   손절: ${self.stop_loss:.2f}")
                logger.info(f"   익절: ${self.take_profit:.2f}")
                logger.info(f"   수량: {self.position_size:.4f} SOL")
                
                # 텔레그램 알림
                msg = f"✅ <b>롱 진입 신호</b>\n\n"
                msg += f"💹 진입가: <b>${entry_price:.2f}</b>\n"
                msg += f"🛑 손절: ${self.stop_loss:.2f}\n"
                msg += f"🎯 익절: ${self.take_profit:.2f}\n"
                msg += f"📊 수량: {self.position_size:.4f} SOL\n"
                msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                send_telegram_message(msg)
                
                self.in_position = True
                self.position_type = 'LONG'
                self.entry_price = entry_price
                self.entry_time = datetime.now()
                
                return True
            
            elif signal_type == 'SHORT':
                risk = self.stop_loss - entry_price
                if risk <= 0:
                    logger.warning(f"⚠️  숏 진입 실패: 위험 값 음수")
                    return False
                
                self.take_profit = entry_price - (risk * RR_RATIO)
                self.position_size = (self.current_balance * self.leverage) / entry_price
                
                # 선물 주문
                order = self.client.futures_create_order(
                    symbol=self.symbol,
                    side='SELL',
                    type='MARKET',
                    quantity=round(self.position_size, 3),
                    leverage=self.leverage
                )
                
                logger.info(f"✅ 숏 진입")
                logger.info(f"   진입가: ${entry_price:.2f}")
                logger.info(f"   손절: ${self.stop_loss:.2f}")
                logger.info(f"   익절: ${self.take_profit:.2f}")
                logger.info(f"   수량: {self.position_size:.4f} SOL")
                
                # 텔레그램 알림
                msg = f"✅ <b>숏 진입 신호</b>\n\n"
                msg += f"💹 진입가: <b>${entry_price:.2f}</b>\n"
                msg += f"🛑 손절: ${self.stop_loss:.2f}\n"
                msg += f"🎯 익절: ${self.take_profit:.2f}\n"
                msg += f"📊 수량: {self.position_size:.4f} SOL\n"
                msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                send_telegram_message(msg)
                
                self.in_position = True
                self.position_type = 'SHORT'
                self.entry_price = entry_price
                self.entry_time = datetime.now()
                
                return True
        
        except BinanceAPIException as e:
            logger.error(f"❌ 주문 실패: {e}")
            send_telegram_message(f"❌ <b>주문 실패</b>\n{str(e)}")
            return False
        except Exception as e:
            logger.error(f"❌ 예상치 못한 오류: {e}")
            send_telegram_message(f"❌ <b>예상치 못한 오류</b>\n{str(e)}")
            return False
    
    def check_exit(self, current_price):
        """익절/손절 확인"""
        if not self.in_position:
            return False
        
        try:
            if self.position_type == 'LONG':
                if current_price <= self.stop_loss:
                    # 손절
                    pnl = (self.stop_loss - self.entry_price) * self.position_size
                    exit_fee = abs(pnl) * FEE
                    net_pnl = pnl - exit_fee
                    self.current_balance += net_pnl
                    
                    logger.info(f"❌ 롱 손절")
                    logger.info(f"   손절가: ${self.stop_loss:.2f}")
                    logger.info(f"   손실: ${net_pnl:.2f}")
                    logger.info(f"   남은 자본: ${self.current_balance:.2f}")
                    
                    # 매매일지 기록
                    duration = datetime.now() - self.entry_time
                    journal.log_trade(
                        trade_type='LONG',
                        entry_price=self.entry_price,
                        exit_price=self.stop_loss,
                        stop_loss=self.stop_loss,
                        take_profit=self.take_profit,
                        pnl=net_pnl,
                        duration=duration
                    )
                    
                    # 텔레그램 알림
                    msg = f"❌ <b>롱 손절</b>\n\n"
                    msg += f"💹 진입가: ${self.entry_price:.2f}\n"
                    msg += f"🛑 손절가: <b>${self.stop_loss:.2f}</b>\n"
                    msg += f"📉 손실: <b>${net_pnl:.2f}</b>\n"
                    msg += f"💰 남은 자본: ${self.current_balance:.2f}\n"
                    msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_telegram_message(msg)
                    
                    self.losing_trades += 1
                    self._record_trade(net_pnl)
                    self._exit_position()
                    return True
                
                elif current_price >= self.take_profit:
                    # 익절
                    pnl = (self.take_profit - self.entry_price) * self.position_size
                    exit_fee = pnl * FEE
                    net_pnl = pnl - exit_fee
                    self.current_balance += net_pnl
                    
                    logger.info(f"✅ 롱 익절")
                    logger.info(f"   익절가: ${self.take_profit:.2f}")
                    logger.info(f"   수익: ${net_pnl:.2f}")
                    logger.info(f"   남은 자본: ${self.current_balance:.2f}")
                    
                    # 매매일지 기록
                    duration = datetime.now() - self.entry_time
                    journal.log_trade(
                        trade_type='LONG',
                        entry_price=self.entry_price,
                        exit_price=self.take_profit,
                        stop_loss=self.stop_loss,
                        take_profit=self.take_profit,
                        pnl=net_pnl,
                        duration=duration
                    )
                    
                    # 텔레그램 알림
                    msg = f"✅ <b>롱 익절</b>\n\n"
                    msg += f"💹 진입가: ${self.entry_price:.2f}\n"
                    msg += f"🎯 익절가: <b>${self.take_profit:.2f}</b>\n"
                    msg += f"📈 수익: <b>${net_pnl:.2f}</b>\n"
                    msg += f"💰 남은 자본: ${self.current_balance:.2f}\n"
                    msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_telegram_message(msg)
                    
                    self.winning_trades += 1
                    self._record_trade(net_pnl)
                    self._exit_position()
                    return True
            
            elif self.position_type == 'SHORT':
                if current_price >= self.stop_loss:
                    # 손절
                    pnl = (self.entry_price - self.stop_loss) * self.position_size
                    exit_fee = abs(pnl) * FEE
                    net_pnl = pnl - exit_fee
                    self.current_balance += net_pnl
                    
                    logger.info(f"❌ 숏 손절")
                    logger.info(f"   손절가: ${self.stop_loss:.2f}")
                    logger.info(f"   손실: ${net_pnl:.2f}")
                    logger.info(f"   남은 자본: ${self.current_balance:.2f}")
                    
                    # 매매일지 기록
                    duration = datetime.now() - self.entry_time
                    journal.log_trade(
                        trade_type='SHORT',
                        entry_price=self.entry_price,
                        exit_price=self.stop_loss,
                        stop_loss=self.stop_loss,
                        take_profit=self.take_profit,
                        pnl=net_pnl,
                        duration=duration
                    )
                    
                    # 텔레그램 알림
                    msg = f"❌ <b>숏 손절</b>\n\n"
                    msg += f"💹 진입가: ${self.entry_price:.2f}\n"
                    msg += f"🛑 손절가: <b>${self.stop_loss:.2f}</b>\n"
                    msg += f"📉 손실: <b>${net_pnl:.2f}</b>\n"
                    msg += f"💰 남은 자본: ${self.current_balance:.2f}\n"
                    msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_telegram_message(msg)
                    
                    self.losing_trades += 1
                    self._record_trade(net_pnl)
                    self._exit_position()
                    return True
                
                elif current_price <= self.take_profit:
                    # 익절
                    pnl = (self.entry_price - self.take_profit) * self.position_size
                    exit_fee = pnl * FEE
                    net_pnl = pnl - exit_fee
                    self.current_balance += net_pnl
                    
                    logger.info(f"✅ 숏 익절")
                    logger.info(f"   익절가: ${self.take_profit:.2f}")
                    logger.info(f"   수익: ${net_pnl:.2f}")
                    logger.info(f"   남은 자본: ${self.current_balance:.2f}")
                    
                    # 매매일지 기록
                    duration = datetime.now() - self.entry_time
                    journal.log_trade(
                        trade_type='SHORT',
                        entry_price=self.entry_price,
                        exit_price=self.take_profit,
                        stop_loss=self.stop_loss,
                        take_profit=self.take_profit,
                        pnl=net_pnl,
                        duration=duration
                    )
                    
                    # 텔레그램 알림
                    msg = f"✅ <b>숏 익절</b>\n\n"
                    msg += f"💹 진입가: ${self.entry_price:.2f}\n"
                    msg += f"🎯 익절가: <b>${self.take_profit:.2f}</b>\n"
                    msg += f"📈 수익: <b>${net_pnl:.2f}</b>\n"
                    msg += f"💰 남은 자본: ${self.current_balance:.2f}\n"
                    msg += f"⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    send_telegram_message(msg)
                    
                    self.winning_trades += 1
                    self._record_trade(net_pnl)
                    self._exit_position()
                    return True
        
        except Exception as e:
            logger.error(f"❌ 익절/손절 확인 오류: {e}")
            send_telegram_message(f"⚠️  <b>익절/손절 오류</b>\n{str(e)}")
        
        return False
    
    def _exit_position(self):
        """포지션 종료"""
        self.in_position = False
        self.position_type = None
        self.sweep_occurred = False
        self.sweep_timer = 0
    
    def _record_trade(self, pnl):
        """거래 기록"""
        self.trades.append({
            'timestamp': datetime.now(),
            'type': self.position_type,
            'entry': self.entry_price,
            'exit': self.take_profit if pnl > 0 else self.stop_loss,
            'pnl': pnl,
            'duration': datetime.now() - self.entry_time
        })
    
    def print_status(self, current_price):
        """상태 출력"""
        print(f"\n{'='*80}")
        print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*80}")
        print(f"현재가: ${current_price:.2f}")
        print(f"자본: ${self.current_balance:.2f} (초기: ${self.initial_balance})")
        print(f"수익률: {(self.current_balance/self.initial_balance - 1)*100:.2f}%")
        
        if self.in_position:
            print(f"\n📊 보유 포지션: {self.position_type}")
            print(f"   진입가: ${self.entry_price:.2f}")
            print(f"   손절: ${self.stop_loss:.2f}")
            print(f"   익절: ${self.take_profit:.2f}")
            
            if self.position_type == 'LONG':
                unrealized = (current_price - self.entry_price) * self.position_size
            else:
                unrealized = (self.entry_price - current_price) * self.position_size
            print(f"   미실현 손익: ${unrealized:.2f}")
        else:
            print(f"\n대기 중... (추세: {['🔄', '📈', '📉'][self.current_trend + 1]})")
        
        print(f"\n📈 거래 통계:")
        print(f"   총 거래: {self.winning_trades + self.losing_trades}")
        print(f"   익절: {self.winning_trades}")
        print(f"   손절: {self.losing_trades}")
        win_rate = (self.winning_trades / (self.winning_trades + self.losing_trades) * 100) if (self.winning_trades + self.losing_trades) > 0 else 0
        print(f"   승률: {win_rate:.1f}%")
        print(f"{'='*80}\n")

# ──────────────────────────────────────────────────
# 메인 루프
# ──────────────────────────────────────────────────

def main():
    logger.info("=" * 80)
    logger.info("🚀 솔라나 자동 매매 봇 시작 (텔레그램 알림 + 매매일지)")
    logger.info("=" * 80)
    
    # 초기화
    client = init_binance_client()
    bot = SolanaBot(client, SYMBOL, INITIAL_BALANCE, LEVERAGE)
    
    logger.info(f"\n📊 전략 설정:")
    logger.info(f"   PIVOT_LOOKBACK: {PIVOT_LOOKBACK}")
    logger.info(f"   RR_RATIO: {RR_RATIO}")
    logger.info(f"   수수료: {FEE*100:.2f}%")
    
    # 봇 실행
    error_count = 0
    max_errors = 5
    
    while True:
        try:
            # OHLCV 데이터 조회 (최근 100개 1시간봉)
            df = fetch_ohlcv(client, SYMBOL, '1h', limit=100)
            
            if df is None:
                error_count += 1
                if error_count >= max_errors:
                    logger.error(f"❌ {max_errors}회 연속 오류로 봇 종료")
                    send_telegram_message(f"❌ <b>봇 종료됨</b>\n{max_errors}회 연속 오류로 인해 봇이 자동 종료되었습니다.")
                    break
                logger.warning(f"⚠️  데이터 조회 실패 ({error_count}/{max_errors})")
                time.sleep(5)
                continue
            
            error_count = 0
            current_price = float(df['close'].iloc[-1])
            
            # 포지션 보유 중 → 익절/손절 확인
            if bot.in_position:
                bot.check_exit(current_price)
            
            # 포지션 미보유 → 신호 분석
            else:
                signal, price = bot.analyze_signal(df)
                if signal:
                    bot.place_order(signal[0], signal[1])
            
            # 상태 출력 (매 1시간마다)
            bot.print_status(current_price)
            
            # 1시간 대기 (다음 캔들)
            time.sleep(3600)
        
        except KeyboardInterrupt:
            logger.info("\n⛔ 사용자가 봇을 종료했습니다.")
            send_telegram_message(f"⛔ <b>봇 종료됨</b>\n사용자가 봇을 종료했습니다.")
            break
        except Exception as e:
            logger.error(f"❌ 예상치 못한 오류: {e}")
            send_telegram_message(f"⚠️  <b>오류 발생</b>\n{str(e)}")
            error_count += 1
            time.sleep(10)
    
    # 종료
    logger.info("\n" + "=" * 80)
    logger.info("📊 최종 통계")
    logger.info("=" * 80)
    logger.info(f"초기 자본: ${INITIAL_BALANCE}")
    logger.info(f"최종 자본: ${bot.current_balance:.2f}")
    logger.info(f"총 수익: ${bot.current_balance - INITIAL_BALANCE:.2f}")
    logger.info(f"수익률: {(bot.current_balance/INITIAL_BALANCE - 1)*100:.2f}%")
    logger.info(f"총 거래: {bot.winning_trades + bot.losing_trades}")
    if (bot.winning_trades + bot.losing_trades) > 0:
        logger.info(f"승률: {(bot.winning_trades/(bot.winning_trades + bot.losing_trades)*100):.1f}%")
    logger.info("=" * 80)
    
    # 최종 보고서 출력
    report = journal.generate_daily_report()
    logger.info(report)
    send_telegram_message(f"<b>일일 거래 보고서</b>\n\n{report}")

if __name__ == '__main__':
    main()
