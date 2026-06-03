# ============================================================
# main.py — 자동매매 전략 메인 실행 파일
# ============================================================
# ⚠️  이 파일은 기존 봇의 main.py에 통합하거나
#     기존 봇에서 이 파일의 함수들을 import하여 사용하세요.
#     API 연결, 웹소켓, 주문 실행 코드는 기존 봇 코드를 사용합니다.
# ============================================================

import logging
import time
from datetime import datetime, timezone

import candle_filter
import risk_manager
import position_manager
from utils import notifier
from strategies import btc_strategy, eth_strategy, xrp_strategy, sol_strategy
from config import SYMBOLS, TIMEFRAME

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("trading.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
# 아래 함수들은 기존 봇의 API 함수로 교체하세요
# ============================================================

def fetch_candles(symbol: str, interval: str, limit: int = 100) -> list:
    """
    거래소에서 캔들 데이터 가져오기
    ⚠️ 기존 봇의 캔들 fetch 함수로 교체 필요
    반환 형식: [[timestamp, open, high, low, close, volume], ...]
    """
    raise NotImplementedError("기존 봇의 fetch_candles 함수로 교체하세요.")


def get_balance() -> float:
    """
    현재 USDT 잔고 조회
    ⚠️ 기존 봇의 잔고 조회 함수로 교체 필요
    """
    raise NotImplementedError("기존 봇의 get_balance 함수로 교체하세요.")


def get_funding_rate(symbol: str) -> float:
    """
    현재 펀딩비 조회 (BTC/ETH용)
    ⚠️ 기존 봇의 펀딩비 조회 함수로 교체 필요
    """
    raise NotImplementedError("기존 봇의 get_funding_rate 함수로 교체하세요.")


def get_btc_dominance_trend() -> str:
    """
    BTC 도미넌스 추세 조회 (ETH 전략 보조 필터)
    ⚠️ 선택사항 — 구현 어려우면 "FLAT" 반환으로 대체 가능
    Returns: "UP" / "DOWN" / "FLAT"
    """
    return "FLAT"


def place_order(symbol: str, direction: str, usdt_amount: float,
                leverage: int, sl_price: float, tp_price: float | None) -> bool:
    """
    주문 실행
    ⚠️ 기존 봇의 주문 실행 함수로 교체 필요
    Returns: True = 성공
    """
    raise NotImplementedError("기존 봇의 place_order 함수로 교체하세요.")


def close_order(symbol: str, direction: str) -> float:
    """
    포지션 청산 주문
    ⚠️ 기존 봇의 청산 함수로 교체 필요
    Returns: 청산가
    """
    raise NotImplementedError("기존 봇의 close_order 함수로 교체하세요.")


def get_current_price(symbol: str) -> float:
    """
    현재가 조회
    ⚠️ 기존 봇의 현재가 조회 함수로 교체 필요
    """
    raise NotImplementedError("기존 봇의 get_current_price 함수로 교체하세요.")


# ============================================================
# 자정 초기화
# ============================================================

def daily_reset(total_balance: float) -> None:
    """
    매일 자정 UTC 실행
    1. 리스크 카운터 초기화
    2. 일봉 바이어스 업데이트
    """
    logger.info("=== 자정 초기화 시작 ===")

    # 리스크 카운터 초기화
    risk_manager.reset_daily()
    candle_filter.reset_bias()

    # 일봉 바이어스 업데이트
    def fetch_daily(symbol):
        return fetch_candles(symbol, "1d", limit=3)

    bias_dict = candle_filter.update_all_bias(fetch_daily)
    notifier.notify_bias_update(bias_dict)

    # 월간 드로우다운 체크
    if risk_manager.check_monthly_drawdown(total_balance):
        notifier.notify_monthly_shutdown(
            1 - total_balance / risk_manager._state["monthly_start_balance"]
        )
        logger.critical("월간 드로우다운 초과. 봇 중단.")

    logger.info("=== 자정 초기화 완료 ===")


# ============================================================
# 시그널 계산 (1시간봉 인터벌)
# ============================================================

def process_signal(coin: str) -> str | None:
    """
    단일 종목 시그널 계산 및 필터링
    Returns: "LONG" / "SHORT" / None
    """
    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]

    # ── 1단계: 전체 매매 가능 여부 ──────────────────────────
    if not risk_manager.is_trading_allowed():
        return None

    # ── 2단계: 일봉 바이어스 확인 ───────────────────────────
    bias = candle_filter.get_bias(coin)
    if bias == "NONE":
        logger.info(f"[{coin}] 도지 캔들. 당일 거래 제한.")
        return None

    # ── 3단계: 포지션 보유 여부 ─────────────────────────────
    if position_manager.has_position(coin):
        logger.info(f"[{coin}] 포지션 보유 중. 시그널 무시.")
        return None

    # ── 4단계: 당일 재진입 가능 여부 ────────────────────────
    if not risk_manager.is_symbol_reentry_allowed(coin):
        logger.info(f"[{coin}] 당일 손절 이력. 재진입 금지.")
        return None

    # ── 5단계: 종목별 전략 시그널 계산 ──────────────────────
    try:
        candles_1h = fetch_candles(symbol, "1h", limit=100)
        signal = None

        if coin == "BTC":
            funding = get_funding_rate(symbol)
            signal = btc_strategy.check_signal(candles_1h, funding_rate=funding)

        elif coin == "ETH":
            btc_candles = fetch_candles(SYMBOLS["BTC"]["symbol"], "1h", limit=100)
            dom_trend = get_btc_dominance_trend()
            signal = eth_strategy.check_signal(candles_1h, btc_candles, dom_trend)

        elif coin == "XRP":
            signal = xrp_strategy.check_signal(candles_1h)

        elif coin == "SOL":
            signal = sol_strategy.check_signal(candles_1h)

    except Exception as e:
        logger.error(f"[{coin}] 시그널 계산 오류: {e}")
        return None

    # ── 6단계: 바이어스 방향 필터링 ──────────────────────────
    if signal and signal != bias:
        logger.info(f"[{coin}] 시그널({signal})이 바이어스({bias})와 불일치. 무시.")
        return None

    return signal


# ============================================================
# 진입 실행
# ============================================================

def execute_entry(coin: str, signal: str) -> None:
    """
    시그널 확인 후 포지션 진입 실행
    """
    cfg = SYMBOLS[coin]
    symbol = cfg["symbol"]

    try:
        total_balance = get_balance()
        candles_1h = fetch_candles(symbol, "1h", limit=100)

        # ATR 계산
        if coin == "BTC":
            atr = btc_strategy.get_current_atr(candles_1h)
        elif coin == "ETH":
            atr = eth_strategy.get_current_atr(candles_1h)
        elif coin == "XRP":
            atr = xrp_strategy.get_current_atr(candles_1h)
        elif coin == "SOL":
            atr = sol_strategy.get_current_atr(candles_1h)

        # 포지션 사이즈 계산
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
            notifier.notify_entry(
                coin, signal, entry_price,
                sl_tp["sl_price"], sl_tp["tp_price"],
                size_info["leverage"]
            )

    except Exception as e:
        logger.error(f"[{coin}] 진입 실행 오류: {e}")


# ============================================================
# 포지션 모니터링 (웹소켓/실시간)
# ============================================================

def monitor_positions() -> None:
    """
    보유 포지션 손절/익절/트레일링 스탑 감시
    웹소켓 또는 주기적 호출로 실행
    """
    positions = position_manager.get_all_positions()

    for coin, pos in positions.items():
        cfg = SYMBOLS[coin]
        symbol = cfg["symbol"]

        try:
            current_price = get_current_price(symbol)
            direction = pos["direction"]
            sl_price = pos["sl_price"]
            tp_price = pos["tp_price"]

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
                (direction == "LONG" and current_price <= sl_price) or
                (direction == "SHORT" and current_price >= sl_price)
            )

            # 익절 체크 (SOL 제외)
            tp_hit = False
            if tp_price:
                tp_hit = (
                    (direction == "LONG" and current_price >= tp_price) or
                    (direction == "SHORT" and current_price <= tp_price)
                )

            if sl_hit:
                close_price = close_order(symbol, direction)
                result = position_manager.close_position(coin, "SL", close_price)
                if result:
                    notifier.notify_close(
                        coin, "SL", close_price,
                        result["pnl_usdt"], result["pnl_pct"]
                    )
                    # 손절 카운터 체크 → 전면 중단 여부
                    if not risk_manager.is_trading_allowed():
                        notifier.notify_daily_halt(
                            risk_manager.get_state()["daily_stop_count"]
                        )

            elif tp_hit:
                close_price = close_order(symbol, direction)
                result = position_manager.close_position(coin, "TP", close_price)
                if result:
                    notifier.notify_close(
                        coin, "TP", close_price,
                        result["pnl_usdt"], result["pnl_pct"]
                    )

        except Exception as e:
            logger.error(f"[{coin}] 포지션 모니터링 오류: {e}")


# ============================================================
# 메인 루프
# ============================================================

def run() -> None:
    """
    봇 메인 실행 루프
    기존 봇의 스케줄러/루프에 통합하여 사용하세요.
    """
    logger.info("전략 시스템 시작")

    last_reset_date = None
    last_signal_hour = None

    while True:
        try:
            now = datetime.now(timezone.utc)

            # ── 자정 초기화 (하루 1번) ────────────────────────
            if last_reset_date != now.date():
                total_balance = get_balance()
                daily_reset(total_balance)
                last_reset_date = now.date()

                # 월초 잔고 설정
                if now.day == 1:
                    risk_manager.set_monthly_start_balance(total_balance)

            # ── 1시간봉 시그널 체크 ───────────────────────────
            if last_signal_hour != now.hour:
                last_signal_hour = now.hour

                for coin in SYMBOLS.keys():
                    signal = process_signal(coin)
                    if signal:
                        execute_entry(coin, signal)

            # ── 포지션 실시간 모니터링 ────────────────────────
            monitor_positions()

            time.sleep(5)  # 5초 간격 모니터링

        except Exception as e:
            logger.error(f"메인 루프 오류: {e}")
            time.sleep(10)


if __name__ == "__main__":
    run()
