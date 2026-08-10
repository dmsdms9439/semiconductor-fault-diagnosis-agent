"""
Kafka 스트리머 자동 실행 래퍼 — 오전 9시(KST)에 자동 종료.

동작:
  - kafka_streamer.py 를 자식 프로세스로 실행(3토픽 produce)
  - 당일 09:00 KST에 도달하면 자식 프로세스를 종료
  - 이미 09:00 이후에 시작되면 아무것도 하지 않고 종료 ("9시까지만" 의미)

Windows 작업 스케줄러 작업 'EtchStreamer'(로그온 시 시작)로 등록되어,
로그인해 있는 동안 아침 9시까지만 데이터를 흘린다. 로그는 logs/streamer.log.
"""

import os
import sys
import time
import subprocess
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
KST = ZoneInfo("Asia/Seoul")


def main():
    now = datetime.now(KST)
    stop = now.replace(hour=9, minute=0, second=0, microsecond=0)

    os.makedirs("logs", exist_ok=True)
    logf = open(os.path.join("logs", "streamer.log"), "a", encoding="utf-8")

    if now >= stop:
        logf.write(f"[{now.isoformat()}] 이미 09:00 이후 — 스트리머 미실행(9시까지만).\n")
        logf.flush(); logf.close()
        return

    logf.write(f"\n=== streamer start {now.isoformat()} → stop {stop.isoformat()} ===\n")
    logf.flush()

    # sys.executable = 이 스크립트를 실행한 venv 파이썬 → 동일 인터프리터로 스트리머 실행
    proc = subprocess.Popen([sys.executable, "kafka_streamer.py"],
                            stdout=logf, stderr=subprocess.STDOUT)
    try:
        while datetime.now(KST) < stop:
            if proc.poll() is not None:
                logf.write(f"[{datetime.now(KST).isoformat()}] 스트리머가 스스로 종료됨.\n")
                break
            time.sleep(20)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        logf.write(f"=== streamer stopped {datetime.now(KST).isoformat()} (09:00 도달) ===\n")
        logf.flush(); logf.close()


if __name__ == "__main__":
    main()
