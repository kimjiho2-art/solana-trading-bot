# ============================================================
# ml_optimizer.py — XGBoost 전략 자동 개선 시스템
# ============================================================
# AWS 프리티어 메모리 보호:
# - 학습 중 봇 신규 진입 일시 중단
# - 최대 500건 배치 제한
# - 학습 완료 후 즉시 메모리 해제
# ============================================================

import gc
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 설정
MIN_TRAIN_SAMPLES = 30       # 최소 학습 데이터 수
MAX_TRAIN_SAMPLES = 500      # 최대 학습 데이터 수 (메모리 절약)
LOSS_STREAK_LIMIT = 8        # 최근 N건 중 손절 비율 트리거
LOSS_STREAK_RATIO = 0.8      # 손절 비율 80% 이상 시 전면 수정

# 최적화된 파라미터 저장 경로
OPTIMIZED_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "config_optimized.json"
)

# 학습 중 플래그 (봇 진입 차단용)
_is_training = False


def is_training() -> bool:
    """현재 학습 중 여부 반환 (봇 진입 차단용)"""
    return _is_training


# ============================================================
# 데이터 전처리
# ============================================================

def _prepare_features(trades: list) -> tuple:
    """
    매매일지 데이터를 XGBoost 학습용 피처로 변환
    Returns: (X, y) — 피처 행렬, 타겟 (1=익절, 0=손절)
    """
    rows = []
    for t in trades:
        try:
            row = {
                # 수치 피처
                "atr": float(t.get("atr") or 0),
                "rsi": float(t.get("rsi") or 50),
                "macd": float(t.get("macd") or 0),
                "volume_ratio": float(t.get("volume_ratio") or 1),
                "funding_rate": float(t.get("funding_rate") or 0),
                "leverage": float(t.get("leverage") or 3),
                "hold_minutes": float(t.get("hold_minutes") or 0),
                "pnl_pct": float(t.get("pnl_pct") or 0),

                # 범주형 피처 (숫자로 변환)
                "direction": 1 if t.get("direction") == "LONG" else 0,
                "supertrend_dir": float(t.get("supertrend_dir") or 0),
                "daily_bias_long": 1 if t.get("daily_bias") == "LONG" else 0,
                "daily_bias_short": 1 if t.get("daily_bias") == "SHORT" else 0,

                # 종목 인코딩
                "symbol_btc": 1 if t.get("symbol") == "BTC" else 0,
                "symbol_eth": 1 if t.get("symbol") == "ETH" else 0,
                "symbol_xrp": 1 if t.get("symbol") == "XRP" else 0,
                "symbol_sol": 1 if t.get("symbol") == "SOL" else 0,

                # 볼린저밴드 위치
                "bb_upper": 1 if t.get("bb_position") == "upper" else 0,
                "bb_lower": 1 if t.get("bb_position") == "lower" else 0,

                # 타겟
                "target": 1 if float(t.get("pnl_usdt") or 0) > 0 else 0,
            }
            rows.append(row)
        except Exception as e:
            logger.warning(f"데이터 변환 오류 (스킵): {e}")
            continue

    if not rows:
        return None, None

    df = pd.DataFrame(rows)
    feature_cols = [c for c in df.columns if c != "target"]
    X = df[feature_cols].values
    y = df["target"].values

    return X, y


# ============================================================
# 손절 패턴 분석
# ============================================================

def analyze_patterns(trades: list) -> dict:
    """
    익절/손절 패턴 분석
    Returns: 분석 결과 dict
    """
    if not trades:
        return {}

    wins = [t for t in trades if float(t.get("pnl_usdt") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl_usdt") or 0) <= 0]

    def safe_avg(items, key):
        vals = [float(t.get(key) or 0) for t in items if t.get(key)]
        return round(sum(vals) / len(vals), 4) if vals else 0

    def most_common(items, key):
        vals = [t.get(key) for t in items if t.get(key)]
        if not vals:
            return None
        return max(set(vals), key=vals.count)

    analysis = {
        "total": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(len(wins) / len(trades), 4) if trades else 0,

        # 익절 패턴
        "win_avg_rsi": safe_avg(wins, "rsi"),
        "win_avg_hold_minutes": safe_avg(wins, "hold_minutes"),
        "win_avg_volume_ratio": safe_avg(wins, "volume_ratio"),
        "win_common_bias": most_common(wins, "daily_bias"),
        "win_common_symbol": most_common(wins, "symbol"),

        # 손절 패턴
        "loss_avg_rsi": safe_avg(losses, "rsi"),
        "loss_avg_hold_minutes": safe_avg(losses, "hold_minutes"),
        "loss_avg_volume_ratio": safe_avg(losses, "volume_ratio"),
        "loss_common_bias": most_common(losses, "daily_bias"),
        "loss_common_symbol": most_common(losses, "symbol"),
    }

    logger.info(f"패턴 분석 완료: 승률 {analysis['win_rate']:.2%}")
    return analysis


# ============================================================
# 전면 수정 트리거 확인
# ============================================================

def check_full_reset_trigger(trades: list) -> bool:
    """
    최근 N건 중 손절 비율 확인
    Returns: True = 전략 전면 수정 필요
    """
    if len(trades) < LOSS_STREAK_LIMIT:
        return False

    recent = trades[-LOSS_STREAK_LIMIT:]
    loss_count = sum(1 for t in recent if float(t.get("pnl_usdt") or 0) <= 0)
    loss_ratio = loss_count / LOSS_STREAK_LIMIT

    logger.info(f"최근 {LOSS_STREAK_LIMIT}건 손절 비율: {loss_ratio:.2%}")

    return loss_ratio >= LOSS_STREAK_RATIO


# ============================================================
# XGBoost 학습 및 파라미터 최적화
# ============================================================

def _optimize_parameters(trades: list, analysis: dict) -> dict:
    """
    분석 결과 기반 파라미터 최적화 제안
    XGBoost 피처 중요도를 활용
    """
    try:
        from xgboost import XGBClassifier
        from sklearn.model_selection import train_test_split

        X, y = _prepare_features(trades)
        if X is None or len(X) < MIN_TRAIN_SAMPLES:
            return {}

        # 데이터 분할
        if len(X) > 10:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
        else:
            X_train, y_train = X, y

        # XGBoost 학습 (메모리 절약 설정)
        model = XGBClassifier(
            n_estimators=50,        # 트리 수 최소화 (메모리 절약)
            max_depth=4,            # 깊이 제한
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric="logloss",
            verbosity=0,
            tree_method="hist",     # 메모리 효율적인 방식
        )
        model.fit(X_train, y_train)

        # 피처 중요도 추출
        feature_names = [
            "atr", "rsi", "macd", "volume_ratio", "funding_rate",
            "leverage", "hold_minutes", "pnl_pct",
            "direction", "supertrend_dir", "daily_bias_long", "daily_bias_short",
            "symbol_btc", "symbol_eth", "symbol_xrp", "symbol_sol",
            "bb_upper", "bb_lower"
        ]
        importance = dict(zip(feature_names, model.feature_importances_))
        top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:5]

        # 파라미터 최적화 제안
        suggestions = {}

        # RSI 기준값 조정
        win_rsi = analysis.get("win_avg_rsi", 50)
        loss_rsi = analysis.get("loss_avg_rsi", 50)
        if win_rsi > 55:
            suggestions["rsi_long_threshold"] = min(win_rsi - 5, 55)
        if loss_rsi < 45:
            suggestions["rsi_short_threshold"] = max(loss_rsi + 5, 45)

        # 거래량 비율 조정
        win_vol = analysis.get("win_avg_volume_ratio", 1.5)
        if win_vol > 1.3:
            suggestions["volume_surge_ratio"] = round(win_vol * 0.9, 2)

        # 손절 ATR 배수 조정 (손절이 많으면 좁힘)
        win_rate = analysis.get("win_rate", 0.5)
        if win_rate < 0.4:
            suggestions["atr_sl_multiplier"] = 1.2   # 손절 좁히기
        elif win_rate > 0.7:
            suggestions["atr_sl_multiplier"] = 1.8   # 손절 넓히기

        suggestions["top_features"] = [f"{k}: {v:.4f}" for k, v in top_features]
        suggestions["win_rate"] = analysis.get("win_rate", 0)
        suggestions["updated_at"] = datetime.now(timezone(timedelta(hours=9))).strftime(
            "%Y-%m-%d %H:%M KST"
        )

        return suggestions

    except Exception as e:
        logger.error(f"XGBoost 학습 오류: {e}")
        return {}

    finally:
        # 메모리 즉시 해제
        try:
            del model, X, y, X_train, y_train
        except Exception:
            pass
        gc.collect()
        logger.info("XGBoost 메모리 해제 완료")


# ============================================================
# 메인 최적화 실행
# ============================================================

def run_optimization(trades: list, notifier=None) -> dict:
    """
    전략 최적화 메인 실행
    매주 일요일 새벽 3시 KST 자동 실행

    Args:
        trades: 전체 매매 기록 (trading_journal.load_all_trades())
        notifier: 텔레그램 알림 모듈

    Returns:
        최적화 결과 dict
    """
    global _is_training

    if len(trades) < MIN_TRAIN_SAMPLES:
        logger.info(f"학습 데이터 부족: {len(trades)}건 (최소 {MIN_TRAIN_SAMPLES}건 필요)")
        return {}

    logger.info(f"전략 최적화 시작 | 데이터: {len(trades)}건")
    _is_training = True

    try:
        # 최대 500건으로 제한 (메모리 절약)
        if len(trades) > MAX_TRAIN_SAMPLES:
            trades = trades[-MAX_TRAIN_SAMPLES:]
            logger.info(f"데이터 최대 {MAX_TRAIN_SAMPLES}건으로 제한")

        # ── 1단계: 전면 수정 트리거 확인 ──────────────────
        if check_full_reset_trigger(trades):
            logger.warning("손절 비율 80% 초과 — 전략 전면 수정 트리거 발동")
            if notifier:
                notifier.notify_bot_shutdown(
                    reason=f"최근 {LOSS_STREAK_LIMIT}건 중 손절 80% 초과 — 전략 전면 수정 필요",
                )
            _is_training = False
            return {"full_reset_required": True}

        # ── 2단계: 패턴 분석 ──────────────────────────────
        analysis = analyze_patterns(trades)

        # ── 3단계: XGBoost 최적화 ─────────────────────────
        suggestions = _optimize_parameters(trades, analysis)

        if not suggestions:
            logger.warning("최적화 제안 없음")
            _is_training = False
            return {}

        # ── 4단계: 결과 저장 ──────────────────────────────
        result = {
            "analysis": analysis,
            "suggestions": suggestions,
            "full_reset_required": False,
        }

        with open(OPTIMIZED_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"최적화 완료. 결과 저장: {OPTIMIZED_CONFIG_PATH}")

        # ── 5단계: 텔레그램 보고 ──────────────────────────
        if notifier:
            _notify_optimization_result(notifier, analysis, suggestions)

        return result

    except Exception as e:
        logger.error(f"최적화 실행 오류: {e}")
        if notifier:
            notifier.notify_bot_error("전략 최적화 오류", str(e))
        return {}

    finally:
        _is_training = False
        gc.collect()


def _notify_optimization_result(notifier, analysis: dict, suggestions: dict) -> None:
    """텔레그램으로 최적화 결과 보고"""
    win_rate = analysis.get("win_rate", 0)
    win_count = analysis.get("win_count", 0)
    loss_count = analysis.get("loss_count", 0)
    total = analysis.get("total", 0)

    # 제안 파라미터 텍스트
    suggestion_lines = ""
    for key, value in suggestions.items():
        if key not in ("top_features", "win_rate", "updated_at"):
            suggestion_lines += f"  {key}: `{value}`\n"

    top_features = suggestions.get("top_features", [])
    feature_lines = "\n".join([f"  {f}" for f in top_features])

    text = (
        f"🤖 *전략 자동 최적화 완료*\n"
        f"─────────────────────────────\n"
        f"분석 데이터: `{total}건`\n"
        f"승률: `{win_rate:.2%}` (익절 {win_count} / 손절 {loss_count})\n\n"
        f"📊 *주요 영향 피처 TOP 5*\n"
        f"{feature_lines}\n\n"
        f"⚙️ *파라미터 조정 제안*\n"
        f"{suggestion_lines}\n"
        f"🕐 {suggestions.get('updated_at', '')}"
    )
    notifier.send_message(text)


# ============================================================
# 최적화된 파라미터 로드
# ============================================================

def load_optimized_config() -> dict:
    """
    저장된 최적화 파라미터 로드
    봇 시작 시 호출하여 config.py 파라미터 보완
    """
    if not os.path.exists(OPTIMIZED_CONFIG_PATH):
        return {}

    try:
        with open(OPTIMIZED_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        suggestions = data.get("suggestions", {})
        logger.info(f"최적화 파라미터 로드 완료: {suggestions}")
        return suggestions
    except Exception as e:
        logger.error(f"최적화 파라미터 로드 실패: {e}")
        return {}


def get_optimized_param(key: str, default):
    """
    특정 최적화 파라미터 반환
    없으면 default 반환
    """
    config = load_optimized_config()
    return config.get(key, default)
