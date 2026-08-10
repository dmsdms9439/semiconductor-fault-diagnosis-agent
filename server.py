"""
FastAPI WebSocket Server — React 프론트엔드와 백엔드 AI 파이프라인 연결 허브

Architecture:
  3-Topic Kafka (sensor-oes, sensor-machine, sensor-rfm)
    → 실시간 병합 (equipment_id + time_step 기준)
    → InferenceEngine(AE+LightGBM) → SHAPExplainer → SHAPAgent(LLM) → Slack
                          ↓                        ↓                ↓
                    WebSocket metrics          shap_data        shap_report
                          ↓                        ↓                ↓
                              React Frontend (App.jsx)

Endpoints:
  WS  /ws/stream         — 실시간 센서 데이터 스트리밍 + AI 분석 결과
  POST /api/rag_search    — GraphRAG 정비 가이드 검색
  GET  /api/system_status — 시스템 상태 조회
  POST /api/slack_test    — Slack 테스트 알림
"""

import asyncio
import json
import os
import time
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional
from collections import defaultdict
from contextlib import asynccontextmanager

import glob
import re
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

# --- Load Environment ---
load_dotenv()
if "OPEN_AI_API_KEY" in os.environ and "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["OPEN_AI_API_KEY"]

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("EtchServer")

# --- AI Engine Globals (loaded once at startup) ---
engine = None
explainer = None
startup_time = None
_worker_task = None  # 상시 워커 asyncio 태스크 핸들

# --- Kafka availability flag ---
KAFKA_AVAILABLE = False
try:
    from confluent_kafka import Consumer as KafkaConsumer
    KAFKA_AVAILABLE = True
except ImportError:
    logger.warning("confluent_kafka not installed. Kafka mode disabled.")


def load_ai_engines():
    """Load inference engine and SHAP explainer (heavy operation, done once)."""
    global engine, explainer
    from inference import InferenceEngine
    from shap_analysis import SHAPExplainer
    engine = InferenceEngine(lgbm_confidence_threshold=0.8)
    explainer = SHAPExplainer(engine.lgb_model, engine.features)
    logger.info("✅ AI Engines loaded successfully.")
    logger.info(f"   Features: {len(engine.features)} sensors")
    logger.info(f"   Base threshold: {engine.base_threshold:.4f}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load models + start always-on worker at startup."""
    global startup_time, _worker_task
    startup_time = time.time()
    load_ai_engines()

    # Postgres 스키마 보장 (없으면 조용히 비활성)
    from monitoring import store
    await asyncio.to_thread(store.init_schema)

    # 상시 워커 기동 (Kafka 소비·추론·적재·방송) — 브라우저와 무관하게 항상 동작
    if os.getenv("WORKER_ENABLED", "true").lower() == "true" and KAFKA_AVAILABLE:
        from worker import run_worker
        _worker_task = asyncio.create_task(run_worker())
        logger.info("🛠️  Always-on worker started.")
    else:
        logger.info("Worker disabled (WORKER_ENABLED=false or Kafka unavailable).")

    yield

    # Shutdown
    if _worker_task is not None:
        _worker_task.cancel()
    await asyncio.to_thread(store.close)
    logger.info("Server shutting down.")


# --- FastAPI App ---
app = FastAPI(
    title="Etch Process Anomaly Detection Server",
    description="반도체 식각 공정 이상 감지 통합 서버",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Connection Manager ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"🔗 WebSocket connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"🔌 WebSocket disconnected. Total: {len(self.active_connections)}")

    async def send_json(self, websocket: WebSocket, data: dict):
        try:
            await websocket.send_json(data)
        except Exception as e:
            logger.error(f"Failed to send WebSocket message: {e}")

    async def broadcast(self, data: dict):
        """접속 중인 모든 뷰어에게 방송. 끊긴 소켓은 안전하게 제거."""
        for ws in list(self.active_connections):
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(ws)

manager = ConnectionManager()


# --- Pydantic Models ---
class RAGSearchRequest(BaseModel):
    query: str
    fault_name: Optional[str] = None

class SlackTestRequest(BaseModel):
    message: str = "Test alert from React Dashboard"


# ==========================================================================
# WebSocket Endpoint — 실시간 모니터링 스트림
# ==========================================================================
@app.websocket("/ws/stream")
async def websocket_stream(
    websocket: WebSocket,
    source: str = Query(default="local", enum=["local", "kafka"]),
    speed: float = Query(default=0.5, ge=0.05, le=5.0),
    slack: bool = Query(default=False)
):
    """
    실시간 센서 데이터 스트리밍 + AI 파이프라인 실행

    Query Parameters:
        source: "local" (CSV 시뮬레이션) or "kafka" (실시간 Kafka)
        speed: 데이터 전송 간격 (초), 기본 0.5
        slack: Slack 알림 활성화 여부
    """
    await manager.connect(websocket)

    try:
        if source == "kafka":
            # Kafka 모드 = 프로덕션. 소비·추론은 상시 워커가 담당하므로
            # 이 연결은 워커의 broadcast를 받기만 하는 '수동 뷰어'다.
            while True:
                # keep-alive: 클라이언트 메시지 대기(제어하지 않음). 끊기면 예외.
                await websocket.receive_text()
        else:
            # Local CSV 모드 = 데모. 브라우저 트리거로 시뮬레이션 스트림 실행(적재 없음).
            await _stream_from_csv(websocket, speed, slack)
    except WebSocketDisconnect:
        logger.info("Client disconnected normally.")
    except Exception as e:
        logger.error(f"WebSocket stream error: {e}")
    finally:
        manager.disconnect(websocket)


async def _stream_from_csv(websocket: WebSocket, speed: float, slack_active: bool):
    """Local CSV 시뮬레이션 (데모 모드) — 10대 장비에 라운드로빈 분배. 적재 안 함."""
    # 데모는 세션마다 신선한 분석을 위해 run 버퍼 초기화
    global _run_buffer
    for i in range(10):
        eq_id = f"EQ-{i+1:02d}"
        if eq_id in _run_buffer:
            del _run_buffer[eq_id]

    csv_path = 'data/test_tstr.csv'
    if not os.path.exists(csv_path):
        # Fallback
        csv_path = 'data/Augmented_Sensor_Data_v4.csv'
    if not os.path.exists(csv_path):
        await manager.broadcast({
            "type": "error",
            "message": f"No data file found. Tried test_tstr.csv and Augmented_Sensor_Data_v4.csv"
        })
        return

    logger.info(f"📊 Loading CSV: {csv_path}")
    test_df = pd.read_csv(csv_path)
    
    # --- [New] Refined Simulation Strategy ---
    # 1. Group by run_id
    grouped = test_df.groupby('run_id')
    normal_runs = []
    fault_rf = None # RF +10
    fault_tcp = None # TCP +20
    
    for rid, group in grouped:
        fn = group['Fault_Name'].iloc[0]
        if fn == 'Normal':
            normal_runs.append(group)
        elif fn == 'RF +10' and fault_rf is None:
            fault_rf = group
        elif fn == 'TCP +20' and fault_tcp is None:
            fault_tcp = group
            
    # 2. Distribute Normal runs to 10 machines
    eq_queues = [[] for _ in range(10)]
    for i, run in enumerate(normal_runs):
        eq_queues[i % 10].append(run)
        
    # 3. Specific placement: RF +10 to EQ-01 (idx 0), TCP +20 to EQ-03 (idx 2)
    # Put them after the first normal run to see some normal state first
    if fault_rf is not None:
        eq_queues[0].insert(1, fault_rf)
    if fault_tcp is not None:
        eq_queues[2].insert(1, fault_tcp)
        
    # Convert list of DataFrames to a single generator or list of rows per equipment
    # Each eq_queues[i] is now a flat list of rows
    flat_queues = []
    for q in eq_queues:
        if not q: 
            flat_queues.append([])
            continue
        flat_queues.append(pd.concat(q).to_dict('records'))
        
    logger.info(f"📊 Simulation ready. EQ-01 gets RF +10, EQ-03 gets TCP +20.")
    logger.info(f"📊 Normal runs distributed: ~{len(normal_runs)//10} runs per machine.")

    stopped_equipments = set() # Track equipments that encountered anomalies
    indices = [0] * 10 # Track current row index for each machine

    while True:
        # Check if all equipments finished or stopped
        active_count = 0
        for i in range(10):
            if f"EQ-{i+1:02d}" not in stopped_equipments and indices[i] < len(flat_queues[i]):
                active_count += 1
        
        if active_count == 0:
            logger.info("🏁 All machines finished or stopped. Resetting indices...")
            indices = [0] * 10
            # If all stopped, we should probably clear stopped_equipments or wait
            if len(stopped_equipments) >= 10:
                 await manager.broadcast({
                    "type": "info",
                    "message": "모든 설비가 이상 감지로 인해 정지되었습니다."
                })
                 while True:
                    await asyncio.sleep(5)
                    await websocket.receive_text()
            continue

        # Cycle through 10 equipments
        for i in range(10):
            eq_id = f"EQ-{i+1:02d}"
            
            # Skip if stopped or finished
            if eq_id in stopped_equipments or indices[i] >= len(flat_queues[i]):
                continue
                
            row = flat_queues[i][indices[i]]
            indices[i] += 1

            # Check for client messages
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.001)
                if msg == "stop": return
                if msg == "reset": 
                    stopped_equipments.clear()
                    indices = [0] * 10
            except (asyncio.TimeoutError, WebSocketDisconnect):
                if isinstance(indices[i], WebSocketDisconnect): return

            metrics = row
            run_name = metrics.get('Run_Name', f'RUN_{i}')
            fault_name = metrics.get('Fault_Name', 'Normal')

            is_anomaly = await _process_and_send(
                metrics, run_name, eq_id, slack_active,
                ground_truth_fault=fault_name, persist=False
            )

            if is_anomaly:
                logger.warning(f"🚨 Anomaly detected on {eq_id}. Stopping equipment.")
                stopped_equipments.add(eq_id)
                await manager.broadcast({
                    "type": "equipment_stop",
                    "equipment_id": eq_id,
                    "message": f"설비 {eq_id}에서 이상이 발견되어 가동이 중지되었습니다."
                })
                # [New] Trigger Deep Analysis immediately
                asyncio.create_task(_trigger_deep_analysis_for_eq(eq_id, slack_active))

        # Control global stream speed
        await asyncio.sleep(max(speed / 10, 0.01)) 


# Kafka 소비·추론 루프는 worker.py(상시 워커)로 이관됨.
# 이 서버 모듈은 파이프라인(_process_and_send 등)과 서빙(WS/REST)만 담당한다.

# 2단계 이상 탐지: 즉시 알림 + Peak MSE 정밀 분석
# {eq_id: {'run_name': str, 'fault': str, 'alerted': bool,
#           'peak_mse': float, 'peak_metrics': dict, 'peak_result': dict}}
_run_buffer: Dict[str, Dict] = {}


async def _process_and_send(
    metrics: Dict[str, Any],
    run_name: str,
    eq_id: str,
    slack_active: bool,
    ground_truth_fault: str = None,
    is_simulation: bool = True,
    persist: bool = False
) -> bool:
    """
    Core AI Pipeline (2단계 이상 탐지):
    
    Phase 1 — 즉시 알림:
      첫 이상 감지 시 바로 대시보드에 "이상 감지" 표시 (LLM 호출 없음, <100ms)
    
    Phase 2 — Peak MSE 정밀 분석:
      Run 종료 시, 해당 Run에서 MSE가 가장 높았던 시점의 데이터로
      SHAP/LLM 분석 실행 → 가장 정확한 원인 진단 리포트 생성
    """
    global _run_buffer

    # 1. AI Inference
    result = engine.predict(metrics)
    if result.get("status") == "ERROR":
        return False

    # 데모 보정 前 AI 원본 판단 보관 (검증/통계용, 리포트 표면엔 노출 안 함)
    ai_is_anomaly = bool(result.get('is_anomaly', False))

    # === 새로운 Run 시작 감지 → 이전 Run의 Peak 분석 실행 ===
    prev_buffer = _run_buffer.get(eq_id)
    if prev_buffer and prev_buffer['run_name'] != run_name:
        # 이전 Run이 Fault였으면 Peak MSE 시점으로 정밀 분석
        if prev_buffer['alerted'] and prev_buffer['peak_metrics'] is not None:
            peak_time = time.strftime("%H:%M:%S")
            logger.info(
                f"🔬 Phase 2: Deep analysis on peak MSE ({prev_buffer['peak_mse']:.4f}) "
                f"for {eq_id} | {prev_buffer['fault']} | {prev_buffer['run_name']}"
            )
            asyncio.create_task(
                _run_anomaly_pipeline(
                    prev_buffer['peak_result'],
                    prev_buffer['peak_metrics'],
                    prev_buffer['run_name'],
                    eq_id,
                    peak_time,
                    slack_active
                )
            )
        # 버퍼 초기화
        _run_buffer[eq_id] = {
            'run_name': run_name,
            'fault': ground_truth_fault or 'Normal',
            'alerted': False,
            'peak_mse': -1.0,
            'peak_metrics': None,
            'peak_result': None,
        }
    elif eq_id not in _run_buffer:
        _run_buffer[eq_id] = {
            'run_name': run_name,
            'fault': ground_truth_fault or 'Normal',
            'alerted': False,
            'peak_mse': -1.0,
            'peak_metrics': None,
            'peak_result': None,
        }

    buf = _run_buffer[eq_id]

    # === Ground Truth 및 데모용 보정 (Simulation/Demo Mode 전용) ===
    # 사용자의 요청: EQ-01, EQ-03 외에는 어떤 경우에도 정지되지 않고 정상으로 유지되어야 함.
    # 1번(EQ-01), 3번(EQ-03) 설비가 아닌 경우 AI의 판단이나 데이터를 무시하고 '정상'으로 표시.
    if eq_id not in ['EQ-01', 'EQ-03']:
        result['is_anomaly'] = False
        result['status'] = 'Normal'
        result['predicted_label'] = 'Normal'
    else:
        # 1, 3번 설비인 경우: 시뮬레이션 모드라면 정답 정보(ground_truth_fault)에 따라 확실하게 고장 표시
        if is_simulation:
            if ground_truth_fault == 'Normal':
                result['is_anomaly'] = False
                result['status'] = 'Normal'
                result['predicted_label'] = 'Normal'
            elif ground_truth_fault is not None:
                result['status'] = ground_truth_fault
                result['is_anomaly'] = True
                result['predicted_label'] = ground_truth_fault
        # 시뮬레이션 모드가 아니더라도(Kafka 등), AI가 판단한 결과를 따르되 1, 3번이 아니면 위에서 이미 걸러짐

    # === Peak MSE 추적 (Fault Run에서 가장 이상이 큰 시점 기록) ===
    if result['is_anomaly'] and result['mse'] > buf['peak_mse']:
        buf['peak_mse'] = result['mse']
        buf['peak_metrics'] = dict(metrics)  # 복사
        buf['peak_result'] = dict(result)    # 복사

    # === Phase 1: 즉시 알림 (Run 내 첫 번째 이상 감지) ===
    if result['is_anomaly'] and not buf['alerted']:
        buf['alerted'] = True
        logger.info(f"⚡ Phase 1: Immediate alert | {eq_id} | {result['status']} | {run_name}")
        # 프론트엔드에 즉시 알림 전송 (Deep Analysis는 나중에)
        asyncio.create_task(manager.broadcast({
            "type": "alert",
            "equipment_id": eq_id,
            "run_name": run_name,
            "status": result['status'],
            "message": f"설비 {eq_id}에서 이상이 감지되었습니다. (진단 중...)"
        }))

    # === 상태 워딩 보정 (사용자 요청: 이상이 있는데 Normal로 보이지 않게) ===
    if result['is_anomaly'] and result['status'] == 'Normal':
        result['status'] = 'Anomaly Detected'

    current_time = time.strftime("%H:%M:%S")

    # 2. Send metrics
    metrics_payload = {
        "type": "metrics",
        "equipment_id": eq_id,
        "run_name": run_name,
        "mse": result['mse'],
        "status": result['status'],
        "confidence": result['confidence'],
        "is_anomaly": result['is_anomaly'],
        "current_threshold": result.get('current_threshold', engine.base_threshold),
        "predicted_label": result.get('predicted_label', 'Normal'),
        "top_candidates": result.get('top_candidates', []),
        "time": current_time
    }
    await manager.broadcast(metrics_payload)

    # === Postgres 적재 (Kafka 상시 워커 경로에서만, 논블로킹) ===
    # CSV 데모 모드는 persist=False → 적재하지 않음.
    if persist:
        from monitoring import store
        asyncio.create_task(asyncio.to_thread(store.log_inference, {
            "equipment_id": eq_id,
            "run_name": run_name,
            "mse": result['mse'],
            "status": result['status'],
            "is_anomaly": bool(result['is_anomaly']),   # 데모 보정 後 (대시보드 일치)
            "ai_is_anomaly": ai_is_anomaly,              # 보정 前 AI 원본
            "predicted_label": result.get('predicted_label', 'Normal'),
            "confidence": result['confidence'],
        }))

    return result['is_anomaly']


async def _trigger_deep_analysis_for_eq(eq_id: str, slack_active: bool):
    """
    설비 정지 등 즉시 분석이 필요한 경우 호출.
    현재 버퍼에 저장된 Peak MSE 데이터를 기반으로 SHAP 파이프라인 실행.
    """
    global _run_buffer
    buf = _run_buffer.get(eq_id)

    if not buf or buf['peak_metrics'] is None:
        logger.warning(f"⚠️ No peak data to analyze for {eq_id}")
        return

    peak_time = time.strftime("%H:%M:%S")
    logger.info(f"🔬 Forced Deep Analysis (Manual/Stop) | {eq_id} | {buf['run_name']}")

    await _run_anomaly_pipeline(
        buf['peak_result'],
        buf['peak_metrics'],
        buf['run_name'],
        eq_id,
        peak_time,
        slack_active
    )


async def _run_anomaly_pipeline(
    result: Dict,
    metrics: Dict,
    run_name: str,
    eq_id: str,
    current_time: str,
    slack_active: bool
):
    """
    이상 감지 시 SHAP → LLM → Slack 파이프라인 실행 (백그라운드 태스크)
    
    이 함수는 asyncio.create_task()로 호출되므로, 내부 에러가
    메인 스트리밍 루프에 영향을 주지 않도록 전체를 try/except로 감싼다.
    """
    try:
        fault_status = result['status']
        predicted_label = result['predicted_label']

        # --- SHAP Analysis ---
        analysis_data = []
        try:
            target_label = predicted_label
            # 'Normal'로 예측되었으나 MSE가 높아 'UNKNOWN FAULT'가 된 경우,
            # SHAP 분석을 위해 상위 후보(Top-1)의 레이블을 사용한다.
            if (predicted_label == 'Normal' or predicted_label == 'UNKNOWN FAULT') and result.get('top_candidates'):
                target_label = result['top_candidates'][0]['label']
                logger.info(f"🔍 Using Top-1 candidate '{target_label}' for SHAP explanation (Original: {predicted_label})")

            pred_idx = list(engine.le.classes_).index(target_label)
            m_df = pd.DataFrame([metrics])
            m_df.columns = m_df.columns.str.strip()
            scaled = engine.scaler.transform(m_df[engine.features])
            analysis_data = explainer.explain(scaled, metrics, pred_idx)
        except Exception as e:
            logger.error(f"❌ SHAP Analysis Failed: {e}")

        # Send SHAP data
        if analysis_data:
            shap_payload = {
                "type": "shap_data",
                "equipment_id": eq_id,
                "time": current_time,
                "run_name": run_name,
                "fault_status": fault_status,
                "analysis_data": analysis_data
            }
            await manager.broadcast(shap_payload)

        # --- LLM + GraphRAG 병렬 실행 ---
        # 사용자 요청에 따라 'UNKNOWN FAULT' 대신 '감지된 결함'으로 명칭을 순화하여 리포트 생성
        display_fault_name = fault_status if fault_status != "UNKNOWN FAULT" else "감지된 결함"
        
        # === 자동 LLM 원인 분석 (비용 발생 지점) ===
        # 무인 24/7 운영에서 OpenAI 요금이 쌓이지 않도록 기본 OFF.
        # AI 원인 분석/정비 가이드가 필요하면 .env 에서 LLM_ANALYSIS_ENABLED=true.
        from agents.llm_guard import openai_enabled, DISABLED_MESSAGE

        if openai_enabled() and os.getenv("LLM_ANALYSIS_ENABLED", "false").lower() == "true":
            # return_exceptions=True 필수 — 하나라도 raise 하면 gather가 즉시 실패해
            # 성공한 쪽 결과까지 버려진다. RAG는 Neo4j Aura(원격)에 의존해 간헐적으로
            # 실패하는데, 그때 SHAP 원인분석까지 같이 날아가면 안 된다.
            shap_res, rag_res = await asyncio.gather(
                asyncio.to_thread(_call_shap_agent, display_fault_name, analysis_data),
                asyncio.to_thread(_call_rag_v2_text, display_fault_name, analysis_data),
                return_exceptions=True,
            )
            if isinstance(shap_res, BaseException):
                logger.error(f"❌ SHAP LLM analysis failed: {shap_res}")
                explanation = f"AI 원인 분석 실패: {shap_res}"
            else:
                explanation = shap_res
            if isinstance(rag_res, BaseException):
                logger.error(f"❌ GraphRAG recommendation failed: {rag_res}")
                recommendation = f"정비 가이드 조회 실패: {rag_res}"
            else:
                recommendation = rag_res
        elif not openai_enabled():
            # 총괄 킬 스위치가 내려간 상태 — RAG 탭도 함께 막혀 있으므로 그렇게 안내한다.
            explanation = DISABLED_MESSAGE
            recommendation = DISABLED_MESSAGE
        else:
            explanation = "자동 LLM 원인 분석이 비활성화되어 있습니다 (비용 절감). SHAP 기여도 그래프는 정상 제공됩니다."
            recommendation = "정비 가이드가 필요하면 RAG 탭에서 조회하거나 .env의 LLM_ANALYSIS_ENABLED=true 로 활성화하세요."

        # Send LLM report
        report_payload = {
            "type": "shap_report",
            "equipment_id": eq_id,
            "time": current_time,
            "run_name": run_name,
            "fault_status": fault_status,
            "explanation": explanation,
            "recommendation": recommendation,
            "top_candidates": result.get('top_candidates', [])
        }
        await manager.broadcast(report_payload)

        # --- Slack Notification ---
        # SHAP 기여도(analysis_data)까지 함께 전송 — LLM 분석이 꺼져 있어도
        # 센서 근거는 그대로 알림에 실린다.
        if slack_active:
            try:
                await asyncio.to_thread(
                    _send_slack_alert, fault_status, run_name, result['mse'],
                    result['confidence'], explanation,
                    analysis_data, recommendation
                )
            except Exception as e:
                logger.error(f"❌ Slack Alert Failed: {e}")

        logger.info(f"✅ Anomaly pipeline completed: {eq_id} | {fault_status} | {run_name}")

    except Exception as e:
        logger.error(f"❌ Background anomaly pipeline crashed for {eq_id}: {e}")


def _call_shap_agent(fault_status: str, analysis_data: list) -> str:
    """Synchronous LLM call (run in thread)."""
    from agents.shap_agent import SHAPAgent
    agent = SHAPAgent()
    return agent.explain_fault(fault_status, analysis_data)


def _call_rag_v2_text(fault_status: str, analysis_data: list) -> str:
    """자동 Phase 2 용 GraphRAG V2 호출 (스레드에서 동기 실행).

    수동 경로(/api/rag_search)와 같은 _call_rag_v2() 를 쓴다. 기존 Slack/WebSocket
    페이로드가 recommendation 을 문자열로 기대하므로 dict 에서 answer 만 꺼낸다.
    """
    result = _call_rag_v2(
        fault_name=fault_status,
        shap_analysis=analysis_data,
        question="이 이상 징후의 원인과 점검 절차를 알려주세요.",
    )
    return result.get("answer", "정비 가이드를 생성하지 못했습니다.")


def _send_slack_alert(fault_name, run_name, mse, confidence, explanation,
                      shap_analysis=None, recommendation=None):
    """Synchronous Slack webhook call (run in thread)."""
    from notifications.slack import SlackNotifier
    notifier = SlackNotifier()
    notifier.send_alert(fault_name, run_name, mse, confidence, explanation,
                        shap_analysis=shap_analysis, recommendation=recommendation)


# ==========================================================================
# REST Endpoints
# ==========================================================================
@app.post("/api/rag_search")
async def rag_search(request: RAGSearchRequest):
    """
    GraphRAG 정비 가이드 검색
    
    RagGuide.jsx에서 호출하는 엔드포인트.
    사용자 질의를 Neo4j Knowledge Graph + LLM으로 처리하여 정비 가이드를 반환합니다.
    """
    query = request.query
    fault_name = request.fault_name

    # 총괄 킬 스위치 — 이 엔드포인트는 질의 1건마다 OpenAI 과금이 발생하므로
    # 에이전트를 만들기 전에 차단한다(생성자 가드보다 앞선 사용자 친화 경로).
    from agents.llm_guard import openai_enabled, DISABLED_MESSAGE
    if not openai_enabled():
        logger.info("RAG search blocked: OPENAI_ENABLED=false")
        return {
            "recommendation": DISABLED_MESSAGE,
            "candidates": [],
            "chain": {},
            "token_estimate": 0,
            "openai_disabled": True,
        }

    try:
        result = await asyncio.to_thread(_call_rag_v2, query, fault_name)
        return {
            "recommendation": result.get("answer", "No answer generated"),
            "candidates": result.get("candidates", []),
            "chain": result.get("chain", {}),
            "token_estimate": result.get("token_estimate", 0)
        }
    except Exception as e:
        logger.error(f"RAG V2 search error: {e}")
        return {"recommendation": f"Error: {str(e)}", "candidates": [], "chain": {}}


def _call_rag_v2(query: str = None, fault_name: str = None,
                 shap_analysis: list = None, question: str = None) -> dict:
    """GraphRAG V2 — 자동 Phase 2 와 /api/rag_search 가 함께 쓰는 유일한 호출부.

    shap_analysis: SHAPExplainer.explain() 의 list 를 그대로 받는다. V2 가 기대하는
                   dict 형식과 KG 센서명 정규화는 shap_list_to_dict 안에서 처리된다.
                   넘기지 않으면 stage1 이 빈 결과를 내고 텍스트 폴백으로 넘어간다.
    fault_name:    LGBM 라벨은 'TCP +30', KG 의 Fault.name 은 'TCP+30' 이라 공백을 지운다.
                   자연어 질의(query)는 _match_by_text 가 공백으로 토큰을 쪼개므로 그대로 둔다.
    """
    from agents.rag_agent_v2 import GraphRAGAgentV2, shap_list_to_dict

    hint = fault_name.replace(" ", "") if fault_name else (query or "")

    agent = GraphRAGAgentV2()
    try:
        return agent.recommend(
            shap_analysis=shap_list_to_dict(shap_analysis),
            fault_name_hint=hint,
            question=question or query or "이 이상 징후의 원인과 점검 절차를 알려주세요.",
        )
    finally:
        agent.close()


@app.get("/api/system_status")
async def system_status():
    """시스템 상태 조회 — 프론트엔드 헤더 바에 표시"""
    uptime = time.time() - startup_time if startup_time else 0

    return {
        "status": "online",
        "uptime_seconds": round(uptime, 1),
        "models": {
            "autoencoder": {
                "type": "Autoencoder (PyTorch)",
                "features": len(engine.features) if engine else 0,
                "threshold": engine.base_threshold if engine else 0
            },
            "classifier": {
                "type": "LightGBM",
                "classes": list(engine.le.classes_) if engine else []
            }
        },
        "pipeline": {
            "kafka_available": KAFKA_AVAILABLE,
            "neo4j_configured": bool(os.getenv("NEO4J_URI")),
            "slack_configured": bool(os.getenv("SLACK_WEBHOOK_URL")),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
            # 총괄 킬 스위치. false면 실시간 파이프라인·RAG 탭 모두 OpenAI를 호출하지 않는다.
            "openai_enabled": os.getenv("OPENAI_ENABLED", "true").lower() == "true",
            # 이 프로세스가 실제로 들고 있는 값. .env를 고쳐도 재시작 전에는
            # 반영되지 않으므로(load_dotenv는 임포트 시 1회) 여기서 확인 가능하게 노출.
            "llm_analysis_enabled": os.getenv("LLM_ANALYSIS_ENABLED", "false").lower() == "true",
            "llm_model": os.getenv("LLM_MODEL", "gpt-4o-mini")
        },
        "active_connections": len(manager.active_connections)
    }


@app.post("/api/slack_test")
async def slack_test(request: SlackTestRequest):
    """Slack 테스트 알림 발송"""
    try:
        await asyncio.to_thread(
            _send_slack_alert,
            "MANUAL TEST", "TEST_FROM_REACT", 0.0, 1.0,
            request.message
        )
        return {"success": True, "message": "Test alert sent to Slack"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==========================================================================
# Daily HTML Report Serving — 일일 리포트 웹페이지 제공
# ==========================================================================
_REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@app.get("/reports", response_class=HTMLResponse)
async def reports_index():
    """생성된 리포트 목록(최신순) — 간단 인덱스 페이지."""
    files = sorted(glob.glob(os.path.join(_REPORTS_DIR, "report_*.html")), reverse=True)
    if not files:
        return HTMLResponse("<h1>아직 생성된 리포트가 없습니다.</h1>", status_code=404)
    links = "".join(
        f'<li><a href="/reports/{os.path.basename(f)[7:-5]}">{os.path.basename(f)[7:-5]}</a></li>'
        for f in files
    )
    return HTMLResponse(
        f"<html><head><meta charset='utf-8'><title>리포트 목록</title></head>"
        f"<body style='font-family:system-ui;max-width:600px;margin:40px auto'>"
        f"<h1>일일 모니터링 리포트</h1><ul>{links}</ul></body></html>"
    )


@app.get("/reports/latest", response_class=HTMLResponse)
async def report_latest():
    """가장 최근 리포트로 리다이렉트 없이 바로 렌더."""
    files = sorted(glob.glob(os.path.join(_REPORTS_DIR, "report_*.html")))
    if not files:
        return HTMLResponse("<h1>아직 생성된 리포트가 없습니다.</h1>", status_code=404)
    with open(files[-1], encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/reports/{date}", response_class=HTMLResponse)
async def report_by_date(date: str):
    """특정 날짜(YYYY-MM-DD) 리포트 HTML 제공."""
    if not _DATE_RE.match(date):  # 경로 조작 방지
        return HTMLResponse("<h1>잘못된 날짜 형식입니다. (YYYY-MM-DD)</h1>", status_code=400)
    path = os.path.join(_REPORTS_DIR, f"report_{date}.html")
    if not os.path.exists(path):
        return HTMLResponse(f"<h1>{date} 리포트를 찾을 수 없습니다.</h1>", status_code=404)
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ==========================================================================
# Health Check
# ==========================================================================
@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": time.time()}


# ==========================================================================
# Entry Point
# ==========================================================================
if __name__ == "__main__":
    import uvicorn
    # 24/7 운영 기본값은 reload=False. 개발 중에는 UVICORN_RELOAD=true 로 켤 수 있음.
    reload_enabled = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8000,
        reload=reload_enabled,
        log_level="info"
    )
