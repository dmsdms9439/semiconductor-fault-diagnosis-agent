"""
상시 워커 — 브라우저와 무관하게 항상 도는 Kafka 소비·추론 계층

역할:
  3-토픽 Kafka Consumer(sensor-oes / sensor-machine / sensor-rfm)를 상시 구독하여
  (equipment_id, run_id, time_step) 키로 병합 → server._process_and_send(persist=True) 호출
  → 추론 결과를 Postgres 적재 + Slack 즉시알림 + 접속 뷰어에 broadcast.

설계 포인트:
  - WebSocket(브라우저)에 의존하지 않음. 구경꾼이 0명이어도 계속 감시·적재.
  - group.id 고정('etch-worker') → 재시작해도 이어서 소비(뷰어성 임시 그룹 아님).
  - run_worker()의 바깥 while로 예외가 나도 5초 후 자가 재시작(24/7 생존).
  - 24/7 모니터링이므로 설비를 영구 정지시키지 않음(적재/감시 지속).
    Phase1 즉시알림·Phase2 심층분석은 _process_and_send 내부에서 자연히 처리됨.

server 모듈은 함수 내부에서 lazy import 하여 순환 임포트를 피한다.
"""

import os
import json
import time
import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger("Worker")

TOPICS = ['sensor-oes', 'sensor-machine', 'sensor-rfm']
BUFFER_TIMEOUT = 10  # 초: 미완성 병합 버퍼 정리 기준


def _worker_config():
    return {
        "speed": float(os.getenv("WORKER_SPEED", "0.5")),
        "slack": os.getenv("WORKER_SLACK", "true").lower() == "true",
        "bootstrap": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        "group_id": os.getenv("WORKER_GROUP_ID", "etch-worker"),
    }


async def run_worker():
    """자가복구 래퍼 — 예외가 나도 죽지 않고 재시작한다(정상 종료만 탈출)."""
    while True:
        try:
            await _consume_and_infer_forever()
        except asyncio.CancelledError:
            logger.info("Worker cancelled (server shutdown).")
            break
        except Exception as e:
            logger.error(f"⚠️ Worker crashed, restarting in 5s: {e}")
            await asyncio.sleep(5)


async def _consume_and_infer_forever():
    """단일 Kafka 소비 세션. 예외 발생 시 run_worker가 재호출한다."""
    from confluent_kafka import Consumer as KafkaConsumer
    import server  # lazy import (순환 방지). 이 시점엔 server 모듈 로드 완료.

    cfg = _worker_config()
    consumer = KafkaConsumer({
        'bootstrap.servers': cfg["bootstrap"],
        'group.id': cfg["group_id"],
        'auto.offset.reset': 'latest',
    })
    consumer.subscribe(TOPICS)
    logger.info(f"🚀 Worker Kafka consumer started. group={cfg['group_id']} topics={TOPICS}")

    # 병합 버퍼: {(eq_id, run_id, step): {'oes': {...}, 'machine': {...}, 'rfm': {...}}}
    merge_buffer = defaultdict(dict)
    buffer_timestamps = {}

    try:
        while True:
            # 블로킹 poll을 스레드로 넘겨 이벤트 루프(방송 등)를 막지 않음
            msg = await asyncio.to_thread(consumer.poll, 0.5)

            if msg is None:
                # Stale 버퍼 정리
                now = time.time()
                stale = [k for k, ts in buffer_timestamps.items()
                         if now - ts > BUFFER_TIMEOUT]
                for k in stale:
                    merge_buffer.pop(k, None)
                    buffer_timestamps.pop(k, None)
                continue

            if msg.error():
                logger.error(f"Kafka error: {msg.error()}")
                continue

            data = json.loads(msg.value().decode('utf-8'))
            eq_id = data.get('equipment_id', 'EQ-01')
            run_id = data.get('run_id', 'UNKNOWN')
            time_step = data.get('time_step', 0)
            source_type = data.get('source_type', 'unknown')
            sensors = data.get('sensors', {})
            fault_name = data.get('fault_name', 'Normal')

            key = (eq_id, run_id, time_step)
            merge_buffer[key][source_type] = sensors
            buffer_timestamps[key] = time.time()

            # 3개 소스가 모두 도착하면 병합 → 추론
            if len(merge_buffer[key]) >= 3:
                merged = {}
                for _, sensor_dict in merge_buffer[key].items():
                    merged.update(sensor_dict)
                merge_buffer.pop(key, None)
                buffer_timestamps.pop(key, None)

                run_name = f"s{run_id}.int"

                # is_simulation=False → 실제 AI 로직 경로 / persist=True → Postgres 적재
                await server._process_and_send(
                    merged, run_name, eq_id, cfg["slack"],
                    ground_truth_fault=fault_name,
                    is_simulation=False,
                    persist=True,
                )
    finally:
        consumer.close()
        logger.info("Worker Kafka consumer closed.")
