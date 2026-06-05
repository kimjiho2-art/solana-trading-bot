# ============================================================
# bot.py — 메인 실행 파일 (기존 봇 인프라 + 새 전략 통합)
# ============================================================
# 실행 방법: python bot.py
# 위치: 저장소 루트 (solana-trading-bot/)
# ============================================================

import gc
import logging
import logging.handlers
import os
import shutil
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from functools import wraps

import ccxt
import pandas as pd

# ── 기존 봇 설정 파일 (키값 그대로 사용) ─────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "config"))
from solana_bot_config import (
    BINANCE_API_KEY,
    BINANCE_SECRET_KEY,
    TIMEFRAME,
)
from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ── 환경변수 설정 (notifier.py용) ────────────────────────
os.environ["TELEGRAM_TOKEN"] = TELEGRAM_BOT_TOKEN
os.environ["TELEGRAM_CHAT_ID"] = str(TELEGRAM_CHAT_ID)

# ── 새 전략 시스템 ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "strategy"))
import candle_filter
import risk_manager
import position_manager
from utils import notifier
from strategies import btc_strategy, eth_strategy, xrp_strategy, sol_strategy
from config import SYMBOLS, TIMEFRAME as STRATEGY_TIMEFRAME
from trading_journal import record_trade, load_all_trades
from ml_optimizer import run_optimization, is_training

# ── 로깅 설정 ─────────────────────────────────────────────
LOG_DIR  = os.path.expanduser("~/solana_bot_new")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
os.makedirs(LOG_DIR, exist_ok=True)

handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5
)
fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(fmt)

logger = logging.getLogger("trading_bot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())

# ── 거래소 전역 객체 ──────────────────────────────────────
exchange = None

# ── KST 타임존 ────────────────────────────────────────────
KST = timezone(timedelta(hours=9))


# ============================================================
# 유틸리티
# ============================================================

def retry(max_retries=3, delay=5):
    """API 재시도 데코레이터 (기존 봇 그대로)"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as e:
                    logger.warning(f"API 재시도 {attempt+1}/{max_retries}: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(delay * (2 ** attempt))
                    else:
                        raise
        return wrapper
    return decorator


def check_disk_space(threshold=95) -> bool:
    """디스크 공간 체크 (기존 봇 그대로)"""
    try:
        usage = shutil.disk_usage("/")
        pct   = usage.used / usage.total * 100
        free  = usage.free / (1024 ** 3)
        logger.info(f"디스크: {pct:.1f}% | 여유: {free:.2f}GB")
        if pct > threshold:
            logger.warning(f"디스크 부족: {pct:.1f}%")
            notifier.notify_bot_error("디스크 부족", f"{pct:.1f}% 사용 중")
            return False
        return True
    except Exception as e:
        logger.error(f"디스크 체크 실패: {e}")
        return True


class GracefulShutdown:
    """종료 신호 처리 (기존 봇 그대로)"""
    def __init__(self):
        self.shutting_down = False
        signal.signal(signal.SIGTERM, self._handler)
        signal.signal(signal.SIGINT,  self._handler)

    def _handler(self, sig, frame):
        logger.info("종료 신호 수신")
        self.shutting_down = True

    def is_shutting_down(self):
        return self.shutting_down


# ============================================================
# 거래소 연결
# ============================================================

@retry(max_retries=3, delay=5)
def connect_binance():
    """Binance 선물 연결 (기존 봇 그대로)"""
    logger.info("Binance Futures 연결 중...")
    exch = ccxt.binance({
        "apiKey"         : BINANCE_API_KEY,
        "secret"         : BINANCE_SECRET_KEY,
        "enableRateLimit": True,
        "timeout"        : 30000,
        "options"        : {"defaultType": "future"},
    })
    exch.load_markets()

    # 4종목 레버리지 설정
    for coin, cfg in SYMBOLS.items():
        symbol = cfg["symbol"]
        leverage = cfg["max_leverage"]
        try:
            exch.set_leverage(leverage, symbol)
            exch.set_margin_mode("isolated", symbol)
            logger.info(f"[{coin}] 레버리지 {leverage}배 / isolated 설정 완료")
        except Exception as e:
            logger.warning(f"[{coin}] 레버리지 설정 실패: {e}")

    logger.info("Binance 연결 성공")
    return exch


# ============================================================
# strategy/main.py에 연동할 API 함수들
# ============================================================

@retry(max_retries=2, delay=3)
def fetch_candles(symbol: str, interval: str, limit: int = 100) -> list:
    """
    캔들 데이터 조회
    반환: [[timestamp_ms, open, high, low, close, volume], ...]
    """
    ohlcv = exchange.fetch_ohlcv(symbol, interval, limit=limit)
    return ohlcv


def get_balance() -> float:
    """USDT 잔고 조회"""
    try:
        bal = exchange.fetch_balance()
        return float(bal["USDT"]["total"])
    except Exception as e:
        logger.error(f"잔고 조회 실패: {e}")
        return 0.0


def get_funding_rate(symbol: str) -> float:
    """펀딩비 조회"""
    try:
        funding = exchange.fetch_funding_rate(symbol)
        return float(funding.get("fundingRate", 0.0))
    except Exception as e:
        logger.warning(f"펀딩비 조회 실패: {e}")
        return 0.0


def get_current_price(symbol: str) -> float:
    """현재가 조회"""
    try:
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        logger.error(f"현재가 조회 실패: {e}")
        return 0.0


def get_btc_dominance_trend() -> str:
    """BTC 도미넌스 추세 (선택적 구현)"""
    return "FLAT"


def place_order(
    symbol: str,
    direction: str,
    usdt_amount: float,
    leverage: int,
    sl_price: float,
    tp_price: float | None,
) -> bool:
    """
    시장가 주문 + 손절/익절 설정
    direction: "LONG" / "SHORT"
    """
    try:
        # 수량 계산
        current_price = get_current_price(symbol)
        notional = usdt_amount * leverage
        qty = notional / current_price
        market = exchange.markets.get(symbol, {})
        min_qty = float(market.get("limits", {}).get("amount", {}).get("min", 0.001))
        qty = max(qty, min_qty)
        qty = float(exchange.amount_to_precision(symbol, qty))

        if qty <= 0:
            logger.warning(f"[{symbol}] 수량 계산 실패")
            return False

        # 가용 잔고 체크
        free_balance = float(exchange.fetch_balance()["USDT"]["free"])
        if free_balance < usdt_amount:
            logger.warning(f"[{symbol}] 가용 잔고 부족 | 필요: {usdt_amount:.2f} | 가용: {free_balance:.2f}")
            return False

        # 시장가 진입
        side = "buy" if direction == "LONG" else "sell"
        exchange.create_market_order(symbol, side, qty)
        logger.info(f"[{symbol}] {direction} 진입 | 수량: {qty} | 가격: ~${current_price:.4f}")
        time.sleep(1)

        # 손절 설정
        sl_side = "sell" if direction == "LONG" else "buy"
        exchange.create_order(
            symbol, "STOP_MARKET", sl_side, qty,
            params={"stopPrice": sl_price, "reduceOnly": True}
        )
        logger.info(f"[{symbol}] 손절 설정: ${sl_price:.4f}")

        # 익절 설정 (SOL은 트레일링 스탑이므로 tp_price 없음)
        if tp_price:
            exchange.create_order(
                symbol, "TAKE_PROFIT_MARKET", sl_side, qty,
                params={"stopPrice": tp_price, "reduceOnly": True}
            )
            logger.info(f"[{symbol}] 익절 설정: ${tp_price:.4f}")

        return True

    except Exception as e:
        logger.error(f"[{symbol}] 주문 실패: {e}\n{traceback.format_exc()}")
        notifier.notify_bot_error(f"[{symbol}] 주문 실패", str(e)[:150])
        return False


def close_order(symbol: str, direction: str) -> float:
    """포지션 청산"""
    try:
        # 현재 포지션 조회
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if float(pos["contracts"]) != 0:
                contracts = abs(float(pos["contracts"]))
                close_side = "sell" if direction == "LONG" else "buy"

                # 미체결 주문 취소
                try:
                    exchange.cancel_all_orders(symbol)
                except Exception:
                    pass

                # 시장가 청산
                exchange.create_market_order(
                    symbol, close_side, contracts,
                    params={"reduceOnly": True}
                )
                close_price = get_current_price(symbol)
                logger.info(f"[{symbol}] 청산 완료 | 가격: ${close_price:.4f}")
                return close_price

        return get_current_price(symbol)

    except Exception as e:
        logger.error(f"[{symbol}] 청산 실패: {e}")
        return get_current_price(symbol)


# ============================================================
# strategy/main.py 함수들 로컬 바인딩
# ============================================================

def _bind_strategy_functions():
    """
    strategy/main.py의 NotImplementedError 함수들을
    이 파일의 실제 함수로 교체
    """
    import strategy.main as sm
    sm.fetch_candles       = fetch_candles
    sm.get_balance         = get_balance
    sm.get_funding_rate    = get_funding_rate
    sm.get_current_price   = get_current_price
    sm.get_btc_dominance_trend = get_btc_dominance_trend
    sm.place_order         = place_order
    sm.close_order         = close_order
    logger.info("전략 함수 바인딩 완료")


# ============================================================
# 자정 초기화
# ============================================================

def sync_positions_from_exchange() -> None:
    """
    봇 시작 시 거래소 실제 포지션 동기화
    중복 진입 방지
    """
    logger.info("거래소 포지션 동기화 시작")
    for coin, cfg in SYMBOLS.items():
        symbol = cfg["symbol"]
        try:
            positions = exchange.fetch_positions([symbol])
            for pos in positions:
                contracts = float(pos.get("contracts") or 0)
                if contracts != 0:
                    direction = "LONG" if pos["side"] == "long" else "SHORT"
                    entry_price = float(pos.get("entryPrice") or 0)
                    if not position_manager.has_position(coin):
                        # sl_price를 안전한 값으로 설정 (모니터링에서 거래소 청산 감지로 처리)
                        safe_sl = 0.001 if direction == "LONG" else 999999999.0
                        position_manager.open_position(
                            symbol=coin,
                            direction=direction,
                            entry_price=entry_price,
                            sl_price=safe_sl,
                            tp_price=None,
                            position_usdt=float(pos.get("initialMargin") or 0),
                            leverage=cfg["max_leverage"],
                        )
                        logger.info(f"[{coin}] 기존 포지션 동기화: {direction} @ {entry_price}")
        except Exception as e:
            logger.warning(f"[{coin}] 포지션 동기화 실패: {e}")
    logger.info("거래소 포지션 동기화 완료")


def daily_reset() -> None:
    """매일 UTC 자정 초기화 (바이낸스 일봉 마감 기준)"""
    logger.info("=== 자정 초기화 시작 ===")

    total_balance = get_balance()
    daily_stats = notifier.get_daily_stats()
    notifier.notify_daily_summary(total_balance)

    risk_manager.reset_daily()
    candle_filter.reset_bias()
    notifier.reset_daily_stats()

    def fetch_daily(symbol):
        return fetch_candles(symbol, "1d", limit=3)

    bias_dict = candle_filter.update_all_bias(fetch_daily)

    notifier.notify_bias_update(
        bias_dict,
        prev_pnl=daily_stats["pnl"],
        prev_trade_count=daily_stats["trade_count"],
        prev_win_count=daily_stats["win_count"],
        prev_loss_count=daily_stats["loss_count"],
        current_balance=total_balance,
    )

    logger.info("=== 자정 초기화 완료 ===")


# ============================================================
# 시그널 처리 (strategy/main.py 연동)
# ============================================================

def process_signal(coin: str) -> str | None:
    """단일 종목 시그널 계산 및 필터링"""
    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]

    # 학습 중이면 진입 차단
    if is_training():
        return None

    # 전체 매매 가능 여부
    if not risk_manager.is_trading_allowed():
        return None

    # 일봉 바이어스 확인
    bias = candle_filter.get_bias(coin)
    if bias == "NONE":
        return None

    # 포지션 보유 여부
    if position_manager.has_position(coin):
        return None

    # 당일 재진입 가능 여부
    if not risk_manager.is_symbol_reentry_allowed(coin):
        return None

    # 종목별 전략 시그널 계산
    try:
        candles_1h = fetch_candles(symbol, "1h", limit=250)
        signal = None

        if coin == "BTC":
            funding = get_funding_rate(symbol)
            signal = btc_strategy.check_signal(candles_1h, funding_rate=funding)
        elif coin == "ETH":
            btc_candles = fetch_candles(SYMBOLS["BTC"]["symbol"], "1h", limit=250)
            signal = eth_strategy.check_signal(candles_1h, btc_candles)
        elif coin == "XRP":
            signal = xrp_strategy.check_signal(candles_1h)
        elif coin == "SOL":
            signal = sol_strategy.check_signal(candles_1h)

    except Exception as e:
        logger.error(f"[{coin}] 시그널 계산 오류: {e}")
        return None

    # 바이어스 방향 필터링
    if signal and signal != bias:
        notifier.notify_signal_ignored(
            coin, signal,
            f"바이어스 불일치 (시그널: {signal} / 바이어스: {bias})"
        )
        return None

    return signal


def execute_entry(coin: str, signal: str) -> None:
    """포지션 진입 실행"""
    from utils.indicators import (
        candles_to_dataframe, calculate_atr,
        calculate_supertrend, calculate_rsi,
    )

    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]

    try:
        total_balance = get_balance()
        candles_1h = fetch_candles(symbol, "1h", limit=250)

        # ATR 계산
        if coin == "BTC":
            atr = btc_strategy.get_current_atr(candles_1h)
        elif coin == "ETH":
            atr = eth_strategy.get_current_atr(candles_1h)
        elif coin == "XRP":
            atr = xrp_strategy.get_current_atr(candles_1h)
        elif coin == "SOL":
            atr = sol_strategy.get_current_atr(candles_1h)

        entry_price = get_current_price(symbol)
        size_info = risk_manager.calculate_position_size(
            coin, entry_price, atr, total_balance
        )
        sl_tp = risk_manager.calculate_sl_tp(coin, entry_price, signal, atr)

        # 주문 실행
        success = place_order(
            symbol=symbol,
            direction=signal,
            usdt_amount=size_info["position_usdt"],
            leverage=size_info["leverage"],
            sl_price=sl_tp["sl_price"],
            tp_price=sl_tp["tp_price"],
        )

        if success:
            position_manager.open_position(
                symbol=coin,
                direction=signal,
                entry_price=entry_price,
                sl_price=sl_tp["sl_price"],
                tp_price=sl_tp["tp_price"],
                position_usdt=size_info["position_usdt"],
                leverage=size_info["leverage"],
            )

            # 시그널 근거 수집
            df = candles_to_dataframe(candles_1h)
            st_df = calculate_supertrend(df, atr_period=10, multiplier=3.0)
            rsi = calculate_rsi(df)
            signal_info = {
                "슈퍼트렌드": f"{'BUY' if signal == 'LONG' else 'SELL'} 전환",
                "RSI": f"{rsi:.2f}",
                "ATR": f"{atr:.4f}",
            }

            notifier.notify_entry(
                coin, signal, entry_price,
                sl_tp["sl_price"], sl_tp["tp_price"],
                size_info["leverage"], size_info["position_usdt"],
                signal_info=signal_info,
                daily_bias=candle_filter.get_bias(coin),
            )

    except Exception as e:
        logger.error(f"[{coin}] 진입 실행 오류: {e}")
        notifier.notify_bot_error(f"[{coin}] 진입 오류", str(e)[:150])


def monitor_positions() -> None:
    """포지션 손절/익절/트레일링 감시"""
    positions = position_manager.get_all_positions()

    for coin, pos in positions.items():
        cfg = SYMBOLS[coin]
        symbol = cfg["symbol"]

        try:
            current_price = get_current_price(symbol)
            direction = pos["direction"]
            sl_price = pos["sl_price"]
            tp_price = pos["tp_price"]
            entry_time = pos["opened_at"]

            # 보유 시간 계산
            try:
                entry_dt = datetime.fromisoformat(entry_time)
                hold_minutes = int(
                    (datetime.now(timezone.utc) - entry_dt).total_seconds() / 60
                )
            except Exception:
                hold_minutes = 0

            # SOL 트레일링 스탑 업데이트
            if cfg["trailing_stop"]:
                candles_1h = fetch_candles(symbol, "1h", limit=20)
                trailing_dist = sol_strategy.get_trailing_distance(candles_1h)
                new_sl = position_manager.update_trailing_stop(
                    coin, current_price, trailing_dist
                )
                if new_sl:
                    sl_price = new_sl

            # 손절 체크
            sl_hit = (
                (direction == "LONG"  and current_price <= sl_price) or
                (direction == "SHORT" and current_price >= sl_price)
            )

            # 익절 체크
            tp_hit = False
            if tp_price:
                tp_hit = (
                    (direction == "LONG"  and current_price >= tp_price) or
                    (direction == "SHORT" and current_price <= tp_price)
                )

            # 거래소 포지션 실제 확인 (SL/TP 거래소에서 자동 청산됐을 경우)
            try:
                exchange_positions = exchange.fetch_positions([symbol])
                exchange_has_position = any(
                    float(p["contracts"]) != 0 for p in exchange_positions
                )
                if not exchange_has_position and position_manager.has_position(coin):
                    # 거래소에서 자동 청산됨
                    # 수익이면 TP, 손실이면 SL로 판단
                    close_price = get_current_price(symbol)
                    pos = position_manager.get_position(coin)
                    if pos["direction"] == "LONG":
                        is_profit = close_price > pos["entry_price"]
                    else:
                        is_profit = close_price < pos["entry_price"]
                    close_type = "TP" if is_profit else "SL"
                    result = position_manager.close_position(coin, close_type, close_price)
                    if result:
                        _handle_close(coin, result, hold_minutes, close_type)
                    continue
            except Exception:
                pass

            if sl_hit:
                close_price = close_order(symbol, direction)
                result = position_manager.close_position(coin, "SL", close_price)
                if result:
                    _handle_close(coin, result, hold_minutes, "SL")

            elif tp_hit:
                close_price = close_order(symbol, direction)
                result = position_manager.close_position(coin, "TP", close_price)
                if result:
                    _handle_close(coin, result, hold_minutes, "TP")

        except Exception as e:
            logger.error(f"[{coin}] 포지션 모니터링 오류: {e}")


def _handle_close(coin: str, result: dict, hold_minutes: int, close_type: str) -> None:
    """청산 후 처리 — 텔레그램 + 매매일지 + 리스크 체크"""
    # 텔레그램 알림
    if close_type == "TP":
        notifier.notify_close_tp(
            coin, result["direction"],
            result["entry_price"], result["close_price"],
            result["pnl_usdt"], result["pnl_pct"],
            hold_minutes,
        )
    else:
        state = risk_manager.get_state()
        notifier.notify_close_sl(
            coin, result["direction"],
            result["entry_price"], result["close_price"],
            result["pnl_usdt"], result["pnl_pct"],
            hold_minutes,
            state["daily_stop_count"],
            2,
        )

    # 매매일지 기록
    try:
        candles_1h = fetch_candles(SYMBOLS[coin]["symbol"], "1h", limit=250)
        from main import record_trade_journal
        record_trade_journal(
            coin, result, candles_1h,
            candle_filter.get_bias(coin),
            get_funding_rate(SYMBOLS[coin]["symbol"]),
        )
    except Exception as e:
        logger.error(f"[{coin}] 매매일지 기록 오류: {e}")

    # 손절 시 전면 중단 체크
    if close_type in ("SL", "TRAILING"):
        if not risk_manager.is_trading_allowed():
            notifier.notify_daily_halt(
                risk_manager.get_state()["daily_stop_count"],
                get_balance(),
            )


# ============================================================
# 메인 루프
# ============================================================

def run() -> None:
    """봇 메인 실행 루프"""
    global exchange

    shutdown = GracefulShutdown()

    logger.info("=" * 70)
    logger.info("자동매매 봇 시작")
    logger.info("BTC / ETH / XRP / SOL 선물 | 슈퍼트렌드 전략")
    logger.info("=" * 70)

    try:
        # 디스크 체크
        if not check_disk_space():
            return

        # 거래소 연결
        exchange = connect_binance()

        # 전략 함수 바인딩
        _bind_strategy_functions()

        # 초기 일봉 바이어스 설정
        def fetch_daily(symbol):
            return fetch_candles(symbol, "1d", limit=3)
        bias_dict = candle_filter.update_all_bias(fetch_daily)

        # 봇 시작 시 거래소 실제 포지션 동기화 (중복 진입 방지)
        sync_positions_from_exchange()

        total_balance = get_balance()
        notifier.send_message(
            f"🚀 *자동매매 봇 시작*\n"
            f"─────────────────\n"
            f"종목: BTC / ETH / XRP / SOL\n"
            f"전략: 슈퍼트렌드 + 보조지표\n"
            f"잔고: `{total_balance:,.0f} USDT`\n"
            f"BTC: {bias_dict.get('BTC')} | ETH: {bias_dict.get('ETH')}\n"
            f"XRP: {bias_dict.get('XRP')} | SOL: {bias_dict.get('SOL')}"
        )

        last_reset_date = None
        last_signal_hour = -1  # 봇 시작 시 즉시 시그널 체크
        last_disk_check = datetime.now()

        while not shutdown.is_shutting_down():

            now_utc = datetime.now(timezone.utc)
            now_kst = datetime.now(KST)

            # ── 디스크 체크 (10분마다) ───────────────────────
            if datetime.now() - last_disk_check > timedelta(minutes=10):
                check_disk_space()
                last_disk_check = datetime.now()

            # ── 자정 초기화 UTC 기준 (바이낸스 일봉 마감 시간과 일치) ──
            if last_reset_date != now_utc.date():
                daily_reset()
                last_reset_date = now_utc.date()

            # ── 주간 XGBoost 최적화 (일요일 새벽 3시 KST) ────
            if now_kst.weekday() == 6 and now_kst.hour == 3 and now_kst.minute < 1:
                trades = load_all_trades()
                result = run_optimization(trades, notifier)
                if result.get("full_reset_required"):
                    notifier.notify_bot_shutdown("전략 전면 수정 필요 — 손절 비율 80% 초과")
                    raise SystemExit("전략 전면 수정 필요")
                gc.collect()

            # ── 1시간봉 시그널 체크 ───────────────────────────
            if last_signal_hour != now_utc.hour:
                last_signal_hour = now_utc.hour

                for coin in SYMBOLS.keys():
                    try:
                        signal = process_signal(coin)
                        if signal:
                            execute_entry(coin, signal)
                    except Exception as e:
                        logger.error(f"[{coin}] 시그널 처리 오류: {e}")
                        notifier.notify_bot_error(f"[{coin}] 시그널 처리 오류", str(e)[:150])

            # ── 포지션 실시간 모니터링 ────────────────────────
            try:
                monitor_positions()
            except Exception as e:
                logger.error(f"포지션 모니터링 오류: {e}")

            time.sleep(5)

    except SystemExit as e:
        logger.critical(f"봇 종료: {e}")

    except Exception as e:
        logger.error(f"치명적 오류: {e}\n{traceback.format_exc()}")
        notifier.notify_bot_error("치명적 오류", f"{type(e).__name__}: {str(e)[:150]}")

    finally:
        logger.info("=" * 70)
        logger.info("자동매매 봇 종료")
        logger.info("=" * 70)
        notifier.notify_bot_shutdown("봇이 종료되었습니다.")


if __name__ == "__main__":
    run()
