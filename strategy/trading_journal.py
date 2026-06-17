# ============================================================
# trading_journal.py — 매매일지 자동 작성 시스템
# ============================================================

import csv
import os
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# 저장 경로 설정
JOURNAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal")
os.makedirs(JOURNAL_DIR, exist_ok=True)

# CSV 컬럼 정의
COLUMNS = [
    "trade_id",           # 매매 ID
    "symbol",             # 종목
    "direction",          # 방향 (LONG/SHORT)
    "entry_time",         # 진입 시각 (KST)
    "exit_time",          # 청산 시각 (KST)
    "hold_minutes",       # 보유 시간 (분)
    "entry_price",        # 진입가
    "exit_price",         # 청산가
    "sl_price",           # 손절가
    "tp_price",           # 목표가
    "exit_type",          # 청산 유형 (TP/SL/TRAILING)
    "pnl_usdt",           # 손익 USDT
    "pnl_pct",            # 손익률 %
    "leverage",           # 레버리지
    "position_usdt",      # 증거금
    "supertrend_dir",     # 슈퍼트렌드 방향 (-1=상승/1=하락)
    "atr",                # ATR 값
    "ema200",             # EMA 200 (BTC용)
    "rsi",                # RSI 값
    "macd",               # MACD 값
    "bb_position",        # 볼린저밴드 위치 (XRP용: upper/middle/lower)
    "volume_ratio",       # 거래량 비율 (현재/평균)
    "daily_bias",         # 전일 일봉 방향
    "funding_rate",       # 펀딩비
    "btc_dominance_trend" # BTC 도미넌스 추세
]


def _now_kst() -> str:
    """현재 시각 KST 반환"""
    kst = timezone(timedelta(hours=9))
    return datetime.now(kst).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_to_kst_str(time_str: str) -> str:
    """
    다양한 형식의 시각 문자열을 KST '%Y-%m-%d %H:%M:%S' 로 통일한다.
    - 타임존이 포함된 ISO 형식(예: 2026-06-17T10:00:00+00:00) → KST로 변환
      (position_manager.open_position 이 UTC ISO 로 저장하므로 이 경로를 탄다)
    - 타임존이 없는 시각(이미 KST 벽시계 시각으로 간주) → 그대로
    - 알 수 없는 형식 → 원본 유지
    """
    kst = timezone(timedelta(hours=9))
    fmt = "%Y-%m-%d %H:%M:%S"
    if not time_str:
        return ""
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is not None:
            # 타임존 정보가 있으면 KST 로 변환
            return dt.astimezone(kst).strftime(fmt)
        # 타임존 정보가 없으면 이미 KST 시각으로 간주 → 시간 이동 없이 그대로
        return dt.strftime(fmt)
    except (ValueError, TypeError):
        return time_str


def _get_journal_path() -> str:
    """월별 CSV 파일 경로 반환"""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    filename = f"trading_journal_{now.strftime('%Y_%m')}.csv"
    return os.path.join(JOURNAL_DIR, filename)


def _get_next_trade_id() -> int:
    """다음 매매 ID 반환"""
    path = _get_journal_path()
    if not os.path.exists(path):
        return 1

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        if not rows:
            return 1
        return int(rows[-1]["trade_id"]) + 1


def _ensure_header(path: str) -> None:
    """CSV 파일이 없으면 헤더 생성"""
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
        logger.info(f"매매일지 파일 생성: {path}")


def record_trade(
    symbol: str,
    direction: str,
    entry_time: str,
    entry_price: float,
    exit_price: float,
    sl_price: float,
    tp_price: float | None,
    exit_type: str,
    pnl_usdt: float,
    pnl_pct: float,
    leverage: int,
    position_usdt: float,
    # 시그널 정보 (XGBoost 학습용)
    supertrend_dir: int = None,
    atr: float = None,
    ema200: float = None,
    rsi: float = None,
    macd: float = None,
    bb_position: str = None,
    volume_ratio: float = None,
    daily_bias: str = None,
    funding_rate: float = None,
    btc_dominance_trend: str = None,
) -> dict:
    """
    매매 1건 기록
    Returns: 기록된 매매 데이터 dict
    """
    path = _get_journal_path()
    _ensure_header(path)

    exit_time = _now_kst()
    # 진입 시각을 KST 표준 형식으로 정규화 (UTC ISO 등 어떤 형식이 들어와도 통일)
    entry_time_kst = _normalize_to_kst_str(entry_time)
    trade_id = _get_next_trade_id()

    # 보유 시간 계산 (분) — entry/exit 모두 동일한 KST 기준이라 정확히 계산됨
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        entry_dt = datetime.strptime(entry_time_kst, fmt)
        exit_dt = datetime.strptime(exit_time, fmt)
        hold_minutes = int((exit_dt - entry_dt).total_seconds() / 60)
    except Exception:
        hold_minutes = 0

    row = {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry_time": entry_time_kst,
        "exit_time": exit_time,
        "hold_minutes": hold_minutes,
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "sl_price": round(sl_price, 6),
        "tp_price": round(tp_price, 6) if tp_price else "",
        "exit_type": exit_type,
        "pnl_usdt": round(pnl_usdt, 2),
        "pnl_pct": round(pnl_pct, 4),
        "leverage": leverage,
        "position_usdt": round(position_usdt, 2),
        "supertrend_dir": supertrend_dir if supertrend_dir is not None else "",
        "atr": round(atr, 6) if atr else "",
        "ema200": round(ema200, 4) if ema200 else "",
        "rsi": round(rsi, 2) if rsi else "",
        "macd": round(macd, 6) if macd else "",
        "bb_position": bb_position if bb_position else "",
        "volume_ratio": round(volume_ratio, 4) if volume_ratio else "",
        "daily_bias": daily_bias if daily_bias else "",
        "funding_rate": round(funding_rate, 6) if funding_rate else "",
        "btc_dominance_trend": btc_dominance_trend if btc_dominance_trend else "",
    }

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writerow(row)

    logger.info(
        f"[매매일지] #{trade_id} {symbol} {direction} {exit_type} | "
        f"손익: {pnl_usdt:+.2f} USDT ({pnl_pct:+.2%})"
    )

    return row


def get_recent_trades(n: int = 10) -> list:
    """
    최근 N건 매매 기록 반환
    """
    path = _get_journal_path()
    if not os.path.exists(path):
        return []

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    return rows[-n:] if len(rows) >= n else rows


def get_monthly_stats() -> dict:
    """
    이번 달 매매 통계 반환
    Returns:
        {
            total: 총 매매 수
            wins: 익절 수
            losses: 손절 수
            total_pnl: 총 손익
            win_rate: 승률
            avg_win: 평균 익절
            avg_loss: 평균 손절
        }
    """
    path = _get_journal_path()
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        return {}

    total = len(rows)
    wins = [r for r in rows if float(r["pnl_usdt"]) > 0]
    losses = [r for r in rows if float(r["pnl_usdt"]) <= 0]
    total_pnl = sum(float(r["pnl_usdt"]) for r in rows)
    win_rate = len(wins) / total if total > 0 else 0
    avg_win = sum(float(r["pnl_usdt"]) for r in wins) / len(wins) if wins else 0
    avg_loss = sum(float(r["pnl_usdt"]) for r in losses) / len(losses) if losses else 0

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
    }


def load_all_trades() -> list:
    """
    전체 매매 기록 반환 (XGBoost 학습용)
    모든 월별 파일을 합쳐서 반환
    """
    all_rows = []

    if not os.path.exists(JOURNAL_DIR):
        return []

    for filename in sorted(os.listdir(JOURNAL_DIR)):
        if filename.startswith("trading_journal_") and filename.endswith(".csv"):
            path = os.path.join(JOURNAL_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                all_rows.extend(list(reader))

    return all_rows
