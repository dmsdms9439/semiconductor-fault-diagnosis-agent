"""
Kafka Multi-Equipment Producer — 3-토픽 센서별 스트리밍

Architecture (실제 공장 시뮬레이션):
  OES 센서 시스템    → Kafka Topic: sensor-oes
  MACHINE 공정 데이터 → Kafka Topic: sensor-machine
  RFM 가상 센서      → Kafka Topic: sensor-rfm

  각 토픽에서 10대 장비가 동시에 자기 웨이퍼 사이클을 시계열로 전송
  서버에서 (equipment_id, time_step) 키로 3개 소스를 실시간 병합

Usage:
  python kafka_streamer.py                    # 기본 설정
  python kafka_streamer.py --speed 0.3        # 0.3초 간격
  python kafka_streamer.py --num-equipment 5  # 5대 장비만
"""

import pandas as pd
import json
import time
import os
import re
import argparse
import threading
import logging
from itertools import cycle
from confluent_kafka import Producer

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KafkaStreamer")

# --- Configuration ---
TOPICS = {
    'oes': 'sensor-oes',
    'machine': 'sensor-machine',
    'rfm': 'sensor-rfm',
}
BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
NUM_EQUIPMENT = 10

# --- Data File Paths ---
DATA_FILES = {
    'oes': 'data/OES_integrated.csv',
    'machine': 'data/MACHINE_integrated.csv',
    'rfm': 'data/RFM_integrated.csv',
}

# Fault label map (Run ID → Fault_Name, from test_tstr.csv)
FAULT_LABEL_FILE = 'data/test_tstr.csv'


def delivery_report(err, msg):
    if err is not None:
        logger.error(f"❌ Message delivery failed: {err}")


def extract_run_id(run_name):
    """Run_Name에서 숫자 ID를 추출: s2901.int → 2901, l2901.txm → 2901"""
    match = re.search(r'(\d+)', str(run_name))
    return match.group(1) if match else None


def load_fault_labels():
    """test_tstr.csv에서 Run ID → Fault_Name 매핑 로드"""
    if not os.path.exists(FAULT_LABEL_FILE):
        logger.warning(f"⚠️ Fault label file not found: {FAULT_LABEL_FILE}")
        return {}
    
    df = pd.read_csv(FAULT_LABEL_FILE, usecols=['Run_Name', 'Fault_Name'])
    labels = {}
    for run_name in df['Run_Name'].unique():
        run_id = extract_run_id(run_name)
        if run_id:
            fault = df[df['Run_Name'] == run_name]['Fault_Name'].iloc[0]
            labels[run_id] = fault
    return labels


def load_sensor_data():
    """
    3개 _integrated 파일을 로드하고 Run ID 기준으로 그룹화
    
    Returns:
        dict: {
            'oes': {run_id: DataFrame, ...},
            'machine': {run_id: DataFrame, ...},
            'rfm': {run_id: DataFrame, ...},
        }
    """
    data = {}
    
    for source_type, file_path in DATA_FILES.items():
        if not os.path.exists(file_path):
            logger.error(f"❌ Data file not found: {file_path}")
            continue
        
        df = pd.read_csv(file_path)
        # 컬럼명 공백 제거
        df.columns = df.columns.str.strip()
        logger.info(f"📊 {source_type.upper()}: {len(df)} rows, "
                     f"{df['Run_Name'].nunique()} runs, {len(df.columns)} columns")
        
        # Run ID 기준으로 그룹화
        runs = {}
        for run_name in df['Run_Name'].unique():
            run_id = extract_run_id(run_name)
            if run_id:
                run_df = df[df['Run_Name'] == run_name].sort_values('Time_Step')
                runs[run_id] = run_df
        
        data[source_type] = runs
    
    return data


def get_common_runs(data):
    """3개 소스 모두에 존재하는 공통 Run ID 추출"""
    run_sets = [set(runs.keys()) for runs in data.values()]
    common = run_sets[0]
    for s in run_sets[1:]:
        common = common & s
    return sorted(common)


def distribute_runs(common_run_ids, fault_labels, num_equipment=10):
    """
    공통 Run ID를 장비에 균등 분배 (Fault 분산)
    
    Returns:
        dict[str, list[str]]: {eq_id: [run_id1, run_id2, ...]}
    """
    normal_runs = []
    fault_runs = []
    
    for run_id in common_run_ids:
        fault = fault_labels.get(run_id, 'Normal')
        if fault != 'Normal':
            fault_runs.append((run_id, fault))
        else:
            normal_runs.append(run_id)
    
    logger.info(f"📊 Common Runs: {len(common_run_ids)} "
                f"(Normal: {len(normal_runs)}, Fault: {len(fault_runs)})")
    
    equipment_runs = {f"EQ-{i+1:02d}": [] for i in range(num_equipment)}
    eq_ids = list(equipment_runs.keys())
    
    # Fault Run 라운드로빈 분배
    for i, (run_id, fault) in enumerate(fault_runs):
        eq_id = eq_ids[i % num_equipment]
        equipment_runs[eq_id].append(run_id)
        logger.info(f"  ⚠️ Fault Run [{run_id}] ({fault}) → {eq_id}")
    
    # Normal Run 라운드로빈 분배
    eq_idx = 0
    for run_id in normal_runs:
        eq_id = eq_ids[eq_idx % num_equipment]
        equipment_runs[eq_id].append(run_id)
        eq_idx += 1
    
    for eq_id, run_list in equipment_runs.items():
        fault_count = sum(1 for r in run_list if fault_labels.get(r, 'Normal') != 'Normal')
        logger.info(f"  {eq_id}: {len(run_list)} runs "
                     f"({fault_count} fault, {len(run_list) - fault_count} normal)")
    
    return equipment_runs


def stream_equipment(producer, eq_id, run_ids, sensor_data, fault_labels, speed, stop_event):
    """
    하나의 장비(스레드)가 3개 토픽에 동시에 시계열 데이터 전송
    
    각 Run에서 3개 소스의 공통 Time_Step만 사용:
    - Time_Step 1 → OES + MACHINE + RFM 각각 별도 토픽으로 전송
    - Time_Step 2 → ...
    """
    if not run_ids:
        return
    
    run_cycle = cycle(run_ids)
    wafer_count = 0
    
    logger.info(f"🚀 {eq_id}: Streaming started ({len(run_ids)} runs)")
    
    while not stop_event.is_set():
        run_id = next(run_cycle)
        fault_name = fault_labels.get(run_id, 'Normal')
        wafer_count += 1
        
        # 3개 소스의 공통 Time_Step 구하기
        time_steps_per_source = {}
        for source_type in ['oes', 'machine', 'rfm']:
            if run_id in sensor_data[source_type]:
                steps = set(sensor_data[source_type][run_id]['Time_Step'].tolist())
                time_steps_per_source[source_type] = steps
        
        if len(time_steps_per_source) < 3:
            continue
        
        common_steps = sorted(
            time_steps_per_source['oes'] & 
            time_steps_per_source['machine'] & 
            time_steps_per_source['rfm']
        )
        
        if not common_steps:
            continue
        
        fault_marker = f" ⚠️ [{fault_name}]" if fault_name != 'Normal' else ""
        logger.info(f"  {eq_id}: Wafer #{wafer_count} - Run {run_id}{fault_marker} "
                     f"({len(common_steps)} common steps)")
        
        for step in common_steps:
            if stop_event.is_set():
                break
            
            timestamp = time.time()
            
            # 3개 토픽에 각각 전송
            for source_type, topic in TOPICS.items():
                source_runs = sensor_data[source_type]
                if run_id not in source_runs:
                    continue
                
                run_df = source_runs[run_id]
                step_row = run_df[run_df['Time_Step'] == step]
                if step_row.empty:
                    continue
                
                row_dict = step_row.iloc[0].to_dict()
                
                # 메타데이터 컬럼 제거, 센서 데이터만 전송
                meta_cols = ['Data_Type', 'Run_Name', 'Time_Step', 
                             'Fault_Name', 'Is_Synthetic', 'Synthesis_Method']
                sensor_values = {k: v for k, v in row_dict.items() 
                                if k not in meta_cols}
                
                payload = {
                    "equipment_id": eq_id,
                    "run_id": run_id,
                    "time_step": int(step),
                    "source_type": source_type,
                    "fault_name": fault_name,
                    "sensors": sensor_values,
                    "timestamp": timestamp,
                }
                
                try:
                    producer.produce(
                        topic,
                        key=f"{eq_id}:{run_id}:{step}".encode('utf-8'),
                        value=json.dumps(payload, default=str).encode('utf-8'),
                        callback=delivery_report
                    )
                except BufferError:
                    producer.flush()
                    producer.produce(
                        topic,
                        key=f"{eq_id}:{run_id}:{step}".encode('utf-8'),
                        value=json.dumps(payload, default=str).encode('utf-8'),
                        callback=delivery_report
                    )
            
            producer.poll(0)
            time.sleep(speed)
        
        # 웨이퍼 교체 대기 시뮬레이션
        if not stop_event.is_set():
            time.sleep(speed * 2)
    
    logger.info(f"🛑 {eq_id}: Stopped after {wafer_count} wafers.")


def run_producer(speed=0.5, num_equipment=10):
    """10대 장비 × 3 토픽 동시 Kafka 스트리밍"""
    
    # 1. Load sensor data from 3 _integrated files
    sensor_data = load_sensor_data()
    if len(sensor_data) < 3:
        logger.error("❌ Not all 3 sensor data files are available!")
        return
    
    # 2. Find common runs
    common_run_ids = get_common_runs(sensor_data)
    logger.info(f"📊 Common Run IDs across all 3 sources: {len(common_run_ids)}")
    
    # 3. Load fault labels
    fault_labels = load_fault_labels()
    
    # 4. Distribute runs to equipment
    equipment_runs = distribute_runs(common_run_ids, fault_labels, num_equipment)
    
    # 5. Create Kafka producer
    conf = {
        'bootstrap.servers': BOOTSTRAP_SERVERS,
        'queue.buffering.max.messages': 100000,
        'queue.buffering.max.kbytes': 1048576,
        'batch.num.messages': 100,
        'linger.ms': 50,
    }
    producer = Producer(conf)
    logger.info(f"🚀 Kafka Producer created (bootstrap: {BOOTSTRAP_SERVERS})")
    logger.info(f"   Topics: {list(TOPICS.values())}")
    
    # 6. Start equipment threads
    stop_event = threading.Event()
    threads = []
    
    for eq_id, run_ids in equipment_runs.items():
        t = threading.Thread(
            target=stream_equipment,
            args=(producer, eq_id, run_ids, sensor_data, fault_labels, speed, stop_event),
            name=f"Thread-{eq_id}",
            daemon=True
        )
        threads.append(t)
        t.start()
    
    logger.info(f"✅ {len(threads)} equipment threads started! "
                f"(speed: {speed}s, 3 topics per step)")
    logger.info(f"   Press Ctrl+C to stop.")
    
    try:
        while True:
            time.sleep(1)
            producer.poll(0)
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopping all equipment threads...")
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        producer.flush(timeout=10)
        logger.info("✅ All threads stopped. Producer flushed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Kafka 3-Topic Multi-Equipment Streamer")
    parser.add_argument('--speed', type=float, default=0.5,
                        help='Time interval between data points (seconds)')
    parser.add_argument('--num-equipment', type=int, default=NUM_EQUIPMENT,
                        help='Number of equipment to simulate')
    parser.add_argument('--bootstrap-servers', type=str, default=BOOTSTRAP_SERVERS,
                        help='Kafka bootstrap servers')
    args = parser.parse_args()
    
    BOOTSTRAP_SERVERS = args.bootstrap_servers
    run_producer(speed=args.speed, num_equipment=args.num_equipment)
