"""
Postgres 적재 계층 — 실시간 추론 결과를 inference_log 테이블에 저장

설계 원칙:
  - 상시 워커(Kafka 경로)에서만 호출 (CSV 데모 모드는 적재 안 함)
  - 논블로킹: server 쪽에서 asyncio.to_thread로 감싸 호출 → WS 스트림 지연 0
  - 방어적: Postgres가 없거나 죽어도 예외를 삼키고 워커는 계속 돈다
  - POSTGRES_DSN 미설정 / psycopg2 미설치 시 → 조용히 no-op (개발 편의)

집계는 Airflow DAG(dags/report_utils.py)가 이 테이블을 읽어서 수행한다.
"""

import os
import logging
import threading

logger = logging.getLogger("MonitoringStore")

# --- psycopg2 가용성 확인 (없어도 서버는 떠야 함) ---
try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
    _PSYCOPG2_AVAILABLE = True
except ImportError:
    _PSYCOPG2_AVAILABLE = False
    logger.warning("psycopg2 not installed. Monitoring persistence disabled.")

_pool = None
_pool_lock = threading.Lock()
_disabled = False  # 초기화 실패 시 반복 시도 방지

# 커넥션 풀 크기. 동시 쓰기 버스트(예: 절전 복귀 후 밀린 메시지 flush)에 대비해 넉넉히.
_MAXCONN = int(os.getenv("POSTGRES_POOL_MAX", "16"))
# 동시 getconn을 풀 크기 이내로 제한 → 초과분은 '거절(exhausted)' 대신 잠깐 '대기'.
_sema = threading.Semaphore(_MAXCONN)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inference_log (
    id              BIGSERIAL PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT now(),
    equipment_id    TEXT NOT NULL,
    run_name        TEXT,
    mse             DOUBLE PRECISION,
    status          TEXT,
    is_anomaly      BOOLEAN,
    ai_is_anomaly   BOOLEAN,
    predicted_label TEXT,
    confidence      DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_log_ts ON inference_log (ts);
CREATE INDEX IF NOT EXISTS idx_log_eq ON inference_log (equipment_id, ts);
"""

INSERT_SQL = """
INSERT INTO inference_log
    (equipment_id, run_name, mse, status, is_anomaly, ai_is_anomaly,
     predicted_label, confidence)
VALUES (%(equipment_id)s, %(run_name)s, %(mse)s, %(status)s, %(is_anomaly)s,
        %(ai_is_anomaly)s, %(predicted_label)s, %(confidence)s);
"""


def _get_dsn():
    return os.getenv("POSTGRES_DSN")


def _ensure_pool():
    """커넥션 풀 lazy 초기화. 실패하면 _disabled로 전환하고 None 반환."""
    global _pool, _disabled
    if _disabled or not _PSYCOPG2_AVAILABLE:
        return None
    if _pool is not None:
        return _pool
    dsn = _get_dsn()
    if not dsn:
        logger.warning("POSTGRES_DSN not set. Monitoring persistence disabled.")
        _disabled = True
        return None
    with _pool_lock:
        if _pool is None:
            try:
                _pool = ThreadedConnectionPool(minconn=1, maxconn=_MAXCONN, dsn=dsn)
                logger.info(f"✅ Postgres connection pool created (maxconn={_MAXCONN}).")
            except Exception as e:
                logger.error(f"❌ Failed to create Postgres pool: {e}")
                _disabled = True
                return None
    return _pool


def init_schema():
    """서버 startup 시 1회 호출 — 테이블/인덱스 보장."""
    pool = _ensure_pool()
    if pool is None:
        return False
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        logger.info("✅ inference_log schema ready.")
        return True
    except Exception as e:
        logger.error(f"❌ init_schema failed: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        if conn:
            pool.putconn(conn)


def log_inference(record: dict):
    """
    단일 추론 결과 1행 적재. (asyncio.to_thread로 감싸 호출됨)

    record keys:
      equipment_id, run_name, mse, status,
      is_anomaly, ai_is_anomaly, predicted_label, confidence

    어떤 예외가 나도 삼킨다 — 적재 실패가 스트림/워커를 멈추면 안 됨.
    """
    pool = _ensure_pool()
    if pool is None:
        return
    # 동시 쓰기를 풀 크기 이내로 제한(초과 시 대기). 5초 내 확보 못하면 이번 건은 포기.
    if not _sema.acquire(timeout=5):
        logger.error("❌ log_inference skipped: could not acquire write slot (5s).")
        return
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor() as cur:
            cur.execute(INSERT_SQL, {
                "equipment_id": record.get("equipment_id"),
                "run_name": record.get("run_name"),
                "mse": record.get("mse"),
                "status": record.get("status"),
                "is_anomaly": record.get("is_anomaly"),
                "ai_is_anomaly": record.get("ai_is_anomaly"),
                "predicted_label": record.get("predicted_label"),
                "confidence": record.get("confidence"),
            })
        conn.commit()
    except Exception as e:
        logger.error(f"❌ log_inference failed (ignored): {e}")
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
    finally:
        if conn:
            try:
                pool.putconn(conn)
            except Exception:
                pass
        _sema.release()


def close():
    global _pool
    if _pool is not None:
        try:
            _pool.closeall()
        except Exception:
            pass
        _pool = None
