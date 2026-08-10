"""
일일 리포트 스케줄 실행 진입점 (Airflow 대체 — Windows 작업 스케줄러/cron에서 호출).

기본: '어제 달력 하루(KST)'를 집계해 Slack 발송.
사용법:
  python scheduled_report.py                 # 어제 하루 → Slack 발송
  python scheduled_report.py 2026-07-24       # 특정 날짜 하루 → Slack 발송
  python scheduled_report.py --no-slack        # 어제 하루 → 콘솔 출력만(발송 안 함, 배선 테스트용)
  python scheduled_report.py 2026-07-25 --no-slack

Airflow DAG(dags/daily_report_dag.py)와 동일한 집계 창·포맷을 사용한다.
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# 프로젝트 루트 기준으로 경로/환경 세팅 (스케줄러가 임의 cwd에서 호출해도 동작)
HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "dags"))
load_dotenv(os.path.join(HERE, ".env"))

KST = ZoneInfo("Asia/Seoul")


def _resolve_window(argv):
    """argv에서 날짜 인자를 찾아 [start, end) 달력 하루를 반환. 없으면 '어제'."""
    date_arg = next((a for a in argv[1:] if not a.startswith("--")), None)
    if date_arg:
        d = datetime.strptime(date_arg, "%Y-%m-%d").replace(tzinfo=KST)
        return d, d + timedelta(days=1)
    today = datetime.now(tz=KST).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1), today


def main():
    start, end = _resolve_window(sys.argv)
    no_slack = "--no-slack" in sys.argv
    day_label = start.strftime("%Y-%m-%d")

    from report_utils import fetch_stats, build_report, run_daily_report

    if no_slack:
        # 배선/포맷 확인용: 발송 없이 콘솔 출력
        stats = fetch_stats(start, end)
        print(build_report(stats, day_label))
    else:
        run_daily_report(start, end)


if __name__ == "__main__":
    main()
