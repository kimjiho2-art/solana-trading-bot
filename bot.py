# ============================================================
# bot.py — 메인 실행 파일 (리플·이더 신호기반 전략)
# ============================================================
# 실행: python bot.py  (저장소 루트)
# 전략: 슈퍼트렌드 단독 + 신호기반 청산 (백테스트 일치)
#   XRP: ATR10/3.0 + 1캔들지연 진입 + 4배 + 25%
#   ETH: ATR14/3.5 + 다음전환대기 진입 + 2배 + 40%
#   청산: 현재 슈퍼트렌드 방향이 포지션과 반대면 즉시 (백테스트와 동일)
#   진입: 전환(flip) 시점에 (delay1=다음봉, wait_next=전환봉)
# ============================================================

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

# ── 기존 봇 설정 (API 키 그대로 재사용) ──────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "config"))
from solana_bot_config import BINANCE_API_KEY, BINANCE_SECRET_KEY
from telegram_config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# ── 새 전략 시스템 ────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "strategy"))
import risk_manager
import position_manager
from utils import notifier
from strategies import xrp_strategy, eth_strategy
from config import SYMBOLS, TIMEFRAME
from trading_journal import record_trade, load_all_trades

# ── 환경변수 (notifier.py용) ─────────────────────────────
os.environ["TELEGRAM_TOKEN"] = TELEGRAM_BOT_TOKEN
os.environ["TELEGRAM_CHAT_ID"] = str(TELEGRAM_CHAT_ID)

# ── 로깅 ──────────────────────────────────────────────────
LOG_DIR  = os.path.expanduser("~/solana_bot_new")
LOG_FILE = os.path.join(LOG_DIR, "trading_bot.log")
os.makedirs(LOG_DIR, exist_ok=True)
handler = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
logger = logging.getLogger("trading_bot")
logger.setLevel(logging.INFO)
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())

exchange = None
KST = timezone(timedelta(hours=9))

STRATEGY = {"XRP": xrp_strategy, "ETH": eth_strategy}


def retry(max_retries=3, delay=5):
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


def check_disk_space(threshold=90) -> bool:
    try:
        usage = shutil.disk_usage("/")
        pct = usage.used / usage.total * 100
        logger.info(f"디스크: {pct:.1f}% | 여유: {usage.free/(1024**3):.2f}GB")
        if pct > threshold:
            notifier.notify_bot_error("디스크 부족", f"{pct:.1f}% 사용 중")
            return False
        return True
    except Exception as e:
        logger.error(f"디스크 체크 실패: {e}")
        return True


class GracefulShutdown:
    def __init__(self):
        self.shutting_down = False
        signal.signal(signal.SIGTERM, self._handler)
        signal.signal(signal.SIGINT, self._handler)
    def _handler(self, sig, frame):
        logger.info("종료 신호 수신")
        self.shutting_down = True
    def is_shutting_down(self):
        return self.shutting_down


@retry(max_retries=3, delay=5)
def connect_binance():
    logger.info("Binance Futures 연결 중...")
    exch = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_SECRET_KEY,
        "enableRateLimit": True,
        "timeout": 30000,
        "options": {"defaultType": "future"},
    })
    exch.load_markets()
    for coin, cfg in SYMBOLS.items():
        try:
            exch.set_leverage(cfg["max_leverage"], cfg["symbol"])
            exch.set_margin_mode("isolated", cfg["symbol"])
            logger.info(f"[{coin}] 레버리지 {cfg['max_leverage']}배 / isolated 설정")
        except Exception as e:
            logger.warning(f"[{coin}] 레버리지 설정 실패: {e}")
    logger.info("Binance 연결 성공")
    return exch


@retry(max_retries=2, delay=3)
def fetch_candles(symbol: str, interval: str, limit: int = 100) -> list:
    return exchange.fetch_ohlcv(symbol, interval, limit=limit)


def get_balance() -> float:
    try:
        bal = exchange.fetch_balance()
        return float(bal["USDT"]["total"])
    except Exception as e:
        logger.error(f"잔고 조회 실패: {e}")
        return 0.0


def get_current_price(symbol: str) -> float:
    try:
        return float(exchange.fetch_ticker(symbol)["last"])
    except Exception as e:
        logger.error(f"현재가 조회 실패: {e}")
        return 0.0


def place_order(symbol: str, direction: str, usdt_amount: float, leverage: int) -> bool:
    try:
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
        side = "buy" if direction == "LONG" else "sell"
        exchange.create_market_order(symbol, side, qty)
        logger.info(f"[{symbol}] {direction} 진입 | 수량: {qty} | ~${current_price:.4f}")
        return True
    except Exception as e:
        logger.error(f"[{symbol}] 주문 실패: {e}\n{traceback.format_exc()}")
        notifier.notify_bot_error(f"[{symbol}] 주문 실패", str(e)[:150])
        return False


def close_order(symbol: str, direction: str) -> float:
    try:
        positions = exchange.fetch_positions([symbol])
        for pos in positions:
            if float(pos["contracts"]) != 0:
                contracts = abs(float(pos["contracts"]))
                close_side = "sell" if direction == "LONG" else "buy"
                try:
                    exchange.cancel_all_orders(symbol)
                except Exception:
                    pass
                exchange.create_market_order(symbol, close_side, contracts, params={"reduceOnly": True})
                close_price = get_current_price(symbol)
                logger.info(f"[{symbol}] 청산 완료 | ${close_price:.4f}")
                return close_price
        return get_current_price(symbol)
    except Exception as e:
        logger.error(f"[{symbol}] 청산 실패: {e}")
        return get_current_price(symbol)


def sync_positions_from_exchange() -> None:
    logger.info("거래소 포지션 동기화 시작")
    for coin, cfg in SYMBOLS.items():
        symbol = cfg["symbol"]
        try:
            positions = exchange.fetch_positions([symbol])
            found = False
            for pos in positions:
                contracts = float(pos.get("contracts") or 0)
                if contracts != 0:
                    found = True
                    direction = "LONG" if pos["side"] == "long" else "SHORT"
                    entry_price = float(pos.get("entryPrice") or 0)
                    if not position_manager.has_position(coin):
                        position_manager.open_position(
                            symbol=coin, direction=direction, entry_price=entry_price,
                            position_usdt=float(pos.get("initialMargin") or 0),
                            leverage=cfg["max_leverage"],
                        )
                        logger.info(f"[{coin}] 기존 포지션 동기화: {direction} @ {entry_price}")
            # 거래소에 포지션 없는데 봇은 있다고 알면 정리
            if not found and position_manager.has_position(coin):
                position_manager.close_position(coin, get_current_price(symbol))
                logger.info(f"[{coin}] 거래소에 포지션 없음 — 봇 기록 정리")
        except Exception as e:
            logger.warning(f"[{coin}] 포지션 동기화 실패: {e}")
    logger.info("거래소 포지션 동기화 완료")


def process_coin(coin: str) -> None:
    """
    단일 코인 신호 처리 (백테스트 로직과 동일).
    - 청산: 포지션 보유 중 현재 슈퍼트렌드 방향이 반대면 즉시 청산
    - 진입: delay1=전환 다음봉, wait_next=전환봉(armed 상태)
    """
    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]
    mode = cfg["exit_mode"]

    candles = fetch_candles(symbol, "1h", limit=100)
    if not candles or len(candles) < 30:
        logger.warning(f"[{coin}] 캔들 부족")
        return

    sig = STRATEGY[coin].get_signal(candles)
    if sig["direction"] is None:
        return

    has_pos = position_manager.has_position(coin)
    pos_dir = position_manager.get_position_direction(coin)

    # 매시간 상태 로그 (투명성 — 무슨 일이 있어도 흔적이 남도록)
    logger.info(
        f"[{coin}] ST방향={sig['direction']} 전환={sig['flipped']} "
        f"보유={'있음('+str(pos_dir)+')' if has_pos else '없음'} "
        f"pending={position_manager.get_pending(coin)} armed={position_manager.is_armed(coin)}"
    )

    # ── delay1 예약 진입 (리플): 지난 봉 예약분 먼저 실행 ──
    if mode == "delay1" and not has_pos:
        pending = position_manager.get_pending(coin)
        if pending:
            _enter(coin, pending)
            position_manager.set_pending(coin, None)
            return

    # ── 1) 청산: 현재 방향이 포지션과 반대 (백테스트와 동일) ──
    if has_pos and sig["direction"] != pos_dir:
        close_price = close_order(symbol, pos_dir)
        result = position_manager.close_position(coin, close_price)
        if result:
            _handle_close(coin, result)
        if mode == "delay1":
            # 리플: 반대방향 다음봉 진입 예약
            position_manager.set_pending(coin, sig["direction"])
        elif mode == "wait_next":
            # 이더: 청산 후 다음 전환까지 대기
            position_manager.set_armed(coin, True)
        return

    # ── 2) 신규 진입 (전환 시점) ──
    if not has_pos:
        if mode == "delay1":
            # 전환 시 다음봉 진입 예약
            if sig["flipped"]:
                position_manager.set_pending(coin, sig["flip_to"])
                logger.info(f"[{coin}] 전환 감지 → 다음봉 {sig['flip_to']} 진입 예약")
        elif mode == "wait_next":
            # armed 상태에서 전환 시 진입 (최초 진입 포함)
            if sig["flipped"] and position_manager.is_armed(coin):
                _enter(coin, sig["flip_to"])
                position_manager.set_armed(coin, False)


def _enter(coin: str, direction: str) -> None:
    if position_manager.has_position(coin):
        logger.info(f"[{coin}] 이미 포지션 보유 — 진입 차단")
        return
    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]
    try:
        total_balance = get_balance()
        size = risk_manager.calculate_position_size(coin, total_balance)
        entry_price = get_current_price(symbol)
        ok = place_order(symbol, direction, size["position_usdt"], size["leverage"])
        if ok:
            position_manager.open_position(
                symbol=coin, direction=direction, entry_price=entry_price,
                position_usdt=size["position_usdt"], leverage=size["leverage"],
            )
            notifier.notify_entry(
                coin, direction, entry_price, 0, None,
                size["leverage"], size["position_usdt"],
                signal_info={"슈퍼트렌드": f"{direction} 방향"},
                daily_bias=direction,
            )
    except Exception as e:
        logger.error(f"[{coin}] 진입 오류: {e}")
        notifier.notify_bot_error(f"[{coin}] 진입 오류", str(e)[:150])


def _handle_close(coin: str, result: dict) -> None:
    close_type = "TP" if result["is_profit"] else "SL"
    try:
        entry_dt = datetime.fromisoformat(result["opened_at"])
        hold_min = int((datetime.now(timezone.utc) - entry_dt).total_seconds() / 60)
    except Exception:
        hold_min = 0

    if result["is_profit"]:
        notifier.notify_close_tp(coin, result["direction"], result["entry_price"],
                                 result["close_price"], result["pnl_usdt"],
                                 result["pnl_pct"], hold_min)
    else:
        notifier.notify_close_sl(coin, result["direction"], result["entry_price"],
                                 result["close_price"], result["pnl_usdt"],
                                 result["pnl_pct"], hold_min, 0, 0)

    try:
        candles = fetch_candles(SYMBOLS[coin]["symbol"], "1h", limit=100)
        _record_journal(coin, result, candles)
    except Exception as e:
        logger.error(f"[{coin}] 매매일지 기록 오류: {e}")


def _record_journal(coin: str, result: dict, candles: list) -> None:
    from utils.indicators import candles_to_dataframe, calculate_atr, calculate_supertrend
    df = candles_to_dataframe(candles)
    atr = calculate_atr(df)
    cfg = SYMBOLS[coin]
    st_df = calculate_supertrend(df, atr_period=cfg["st_atr_period"], multiplier=cfg["st_multiplier"])
    st_dir = int(st_df["supertrend_dir"].iloc[-1])
    close_type = "TP" if result["is_profit"] else "SL"
    try:
        record_trade(
            symbol=coin, direction=result["direction"],
            entry_time=result["opened_at"], entry_price=result["entry_price"],
            exit_price=result["close_price"], sl_price=0, tp_price=None,
            exit_type=close_type, pnl_usdt=result["pnl_usdt"], pnl_pct=result["pnl_pct"],
            leverage=result["leverage"], position_usdt=result["position_usdt"],
            supertrend_dir=st_dir, atr=atr, ema200=None, rsi=None, macd=None,
            bb_position=None, volume_ratio=None, daily_bias=result["direction"],
            funding_rate=0.0,
        )
        total = len(load_all_trades())
        notifier.notify_journal_recorded(coin, result["direction"], close_type,
                                         result["pnl_usdt"], total, min_required=0)
    except Exception as e:
        logger.error(f"[{coin}] 매매일지 record_trade 오류: {e}")


def run() -> None:
    global exchange
    shutdown = GracefulShutdown()

    logger.info("=" * 70)
    logger.info("자동매매 봇 시작 — 리플·이더 슈퍼트렌드 신호기반")
    logger.info("=" * 70)

    try:
        if not check_disk_space():
            return
        exchange = connect_binance()
        sync_positions_from_exchange()

        # wait_next(이더) 초기 armed (시작 후 첫 전환부터 진입)
        for coin, cfg in SYMBOLS.items():
            if cfg["exit_mode"] == "wait_next" and not position_manager.has_position(coin):
                position_manager.set_armed(coin, True)

        total_balance = get_balance()
        notifier.send_message(
            f"🚀 *자동매매 봇 시작 (신규 전략)*\n"
            f"─────────────────\n"
            f"종목: 리플 / 이더\n"
            f"전략: 슈퍼트렌드 단독 + 신호기반 청산\n"
            f"리플 4배 25% / 이더 2배 40%\n"
            f"잔고: `{total_balance:,.2f} USDT`"
        )

        last_signal_hour = -1
        last_disk_check = datetime.now()

        while not shutdown.is_shutting_down():
            now_utc = datetime.now(timezone.utc)

            if datetime.now() - last_disk_check > timedelta(minutes=10):
                check_disk_space()
                last_disk_check = datetime.now()

            if last_signal_hour != now_utc.hour and now_utc.minute >= 1:
                last_signal_hour = now_utc.hour
                # 매시간 거래소 포지션 재동기화 (인식 누락 방지)
                try:
                    sync_positions_from_exchange()
                except Exception as e:
                    logger.warning(f"재동기화 실패: {e}")
                for coin in SYMBOLS.keys():
                    try:
                        process_coin(coin)
                    except Exception as e:
                        logger.error(f"[{coin}] 신호 처리 오류: {e}\n{traceback.format_exc()}")
                        notifier.notify_bot_error(f"[{coin}] 신호 처리 오류", str(e)[:150])

            time.sleep(5)

    except SystemExit as e:
        logger.critical(f"봇 종료: {e}")
    except Exception as e:
        logger.error(f"치명적 오류: {e}\n{traceback.format_exc()}")
        notifier.notify_bot_error("치명적 오류", f"{type(e).__name__}: {str(e)[:150]}")
    finally:
        logger.info("자동매매 봇 종료")
        notifier.notify_bot_shutdown("봇이 종료되었습니다.")


if __name__ == "__main__":
    run()
