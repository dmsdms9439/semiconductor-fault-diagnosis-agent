"""
일일 리포트 집계·포맷 유틸 — Airflow DAG(daily_report_dag.py)와 분리해 단위 테스트 가능하게 구성.

데이터 원천: Postgres inference_log (상시 워커가 Kafka 경로에서 적재).
집계 창(start, end)은 DAG의 data_interval(어제 00:00~24:00 KST)로 주입된다.

의존성: psycopg2, requests, notifications.slack (PYTHONPATH=/opt/project 로 노출).
"""

import os
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2

logger = logging.getLogger("DailyReport")

KST = ZoneInfo("Asia/Seoul")

# ---- SQL ----
# 리포트에서 '이상'으로 집계하는 기준: AE가 이상 감지 + 분류기가 실제 결함으로 분류한 것만.
# AE만 반응하고 분류기는 Normal이라 한 케이스(구 '미분류')는 리포트에서 이상으로 치지 않는다(정상 취급).
REAL_ANOM = ("is_anomaly IS TRUE AND predicted_label IS NOT NULL "
             "AND predicted_label NOT IN ('Normal', 'UNKNOWN FAULT')")

Q_TOTALS = """
SELECT count(*)                                        AS total,
       count(*) FILTER (WHERE is_anomaly IS TRUE)      AS anomaly,
       count(*) FILTER (WHERE is_anomaly IS NOT TRUE)  AS normal,
       min(ts)                                         AS min_ts,
       max(ts)                                         AS max_ts
FROM inference_log
WHERE ts >= %(start)s AND ts < %(end)s;
"""

# 설비별·결함라벨별 '이상 Run 수'. 실제 결함으로 분류된 이상만 집계.
Q_EQUIP_FAULTS = f"""
WITH run_label AS (
    SELECT equipment_id, run_name,
           mode() WITHIN GROUP (ORDER BY predicted_label) AS label
    FROM inference_log
    WHERE ts >= %(start)s AND ts < %(end)s AND {REAL_ANOM}
    GROUP BY equipment_id, run_name
)
SELECT equipment_id, label, count(*) AS occurrences
FROM run_label
GROUP BY equipment_id, label
ORDER BY equipment_id, occurrences DESC, label;
"""

Q_MAX_MSE = """
SELECT equipment_id, mse, ts
FROM inference_log
WHERE ts >= %(start)s AND ts < %(end)s AND mse IS NOT NULL
ORDER BY mse DESC
LIMIT 1;
"""


def _dsn():
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN 환경변수가 설정되지 않았습니다.")
    return dsn


def disp_fault(label: str) -> str:
    """이상 행의 결함 표시 라벨. 분류기가 못 잡은 이상(Normal/UNKNOWN FAULT)은 '미분류'로.

    오토인코더가 이상으로 감지했지만 LightGBM이 특정 결함으로 분류하지 못한 경우
    predicted_label 이 'Normal' 또는 'UNKNOWN FAULT' 로 남는다 → 사용자 혼란 방지 위해 '미분류'.
    """
    if label in (None, "Normal", "UNKNOWN FAULT"):
        return "미분류"
    return label


def fetch_stats(start: datetime, end: datetime) -> dict:
    """집계 창 [start, end)의 통계를 dict로 반환."""
    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(Q_TOTALS, {"start": start, "end": end})
            total, anomaly, normal, min_ts, max_ts = cur.fetchone()

            cur.execute(Q_EQUIP_FAULTS, {"start": start, "end": end})
            equip_rows = cur.fetchall()  # [(eq_id, label, occurrences), ...]

            cur.execute(Q_MAX_MSE, {"start": start, "end": end})
            max_row = cur.fetchone()  # (eq_id, mse, ts) or None
    finally:
        conn.close()

    # 설비별 결함 묶기 (표시 라벨로 병합 — 'Normal'/'UNKNOWN FAULT' → '미분류')
    equipment = {}  # eq_id -> {"total": int, "breakdown": [(label, n), ...]}
    for eq_id, label, occ in equip_rows:
        disp = disp_fault(label)
        e = equipment.setdefault(eq_id, {"total": 0, "_bd": {}})
        e["total"] += occ
        e["_bd"][disp] = e["_bd"].get(disp, 0) + occ
    for eq_id, e in equipment.items():
        e["breakdown"] = sorted(e.pop("_bd").items(), key=lambda kv: -kv[1])

    return {
        "total": total or 0,
        "anomaly": anomaly or 0,
        "normal": normal or 0,
        "min_ts": min_ts,
        "max_ts": max_ts,
        "equipment": equipment,
        "max_mse": {
            "equipment_id": max_row[0],
            "mse": max_row[1],
            "ts": max_row[2],
        } if max_row else None,
    }


def _fmt_uptime(min_ts, max_ts) -> str:
    """데이터 구간(max_ts - min_ts) → 'N시간 M분'."""
    if not min_ts or not max_ts:
        return "0시간 0분"
    delta = max_ts - min_ts
    mins = int(delta.total_seconds() // 60)
    return f"{mins // 60}시간 {mins % 60}분"


def build_report(stats: dict, day_label: str) -> str:
    """새 확정 포맷대로 한국어 리포트 문자열 생성."""
    total = stats["total"]
    line = "━━━━━━━━━━━━━━━━━━━━━━━━"
    header = f"📊 일일 모니터링 리포트 ({day_label})\n{line}"

    if total == 0:
        return (f"{header}\n\n"
                "어제 수집된 데이터가 없습니다. (상시 워커/Kafka 스트림 상태를 확인하세요.)")

    anomaly = stats["anomaly"]
    normal = stats["normal"]
    n_pct = (normal / total * 100) if total else 0
    a_pct = (anomaly / total * 100) if total else 0

    parts = [header, ""]
    parts.append("📈 전체 현황")
    parts.append(f"  • 총 처리: {total:,}건")
    parts.append(f"  • 정상: {normal:,}건 ({n_pct:.1f}%)")
    parts.append(f"  • 이상: {anomaly:,}건 ({a_pct:.1f}%)")
    parts.append("")

    parts.append("🏭 설비별 이상 감지")
    equipment = stats["equipment"]
    if not equipment:
        parts.append("  • 이상 감지 설비 없음")
    else:
        for eq_id in sorted(equipment):
            e = equipment[eq_id]
            bd = ", ".join(f"{lbl}: {n}" for lbl, n in e["breakdown"])
            parts.append(f"  • {eq_id}: {e['total']}회 ({bd})")
        parts.append("  • 나머지 설비: 정상 가동")
    parts.append("")

    mm = stats["max_mse"]
    if mm and mm["mse"] is not None:
        t_kst = mm["ts"].astimezone(KST).strftime("%H:%M:%S")
        parts.append(f"⚠️ 최고 MSE: {mm['mse']:.3f} ({mm['equipment_id']}, {t_kst})")
    parts.append("")

    parts.append(f"⏱ 시스템 가동 시간: {_fmt_uptime(stats['min_ts'], stats['max_ts'])}")
    return "\n".join(parts)


def run_daily_report(start: datetime, end: datetime) -> str:
    """집계 → 포맷 → Slack 발송. DAG 단일 태스크에서 호출. 리포트 텍스트 반환."""
    day_label = start.astimezone(KST).strftime("%Y-%m-%d")
    stats = fetch_stats(start, end)
    report = build_report(stats, day_label)

    # 리치 HTML 리포트 저장 + Slack 텍스트에 서버 링크 삽입
    try:
        from report_html import write_html_report
        write_html_report(start, end)
        base = os.getenv("REPORT_BASE_URL", "http://localhost:8000").rstrip("/")
        report += f"\n\n<{base}/reports/{day_label}|📊 상세 리포트 보기>"
    except Exception as e:
        logger.error("HTML report generation failed: %s", e)

    logger.info("Daily report:\n%s", report)
    from notifications.slack import SlackNotifier
    SlackNotifier().send_daily_summary(report)
    return report


if __name__ == "__main__":
    # 로컬 테스트: 최근 24시간
    logging.basicConfig(level=logging.INFO)
    _end = datetime.now(tz=KST)
    _start = _end - timedelta(hours=24)
    print(run_daily_report(_start, _end))
