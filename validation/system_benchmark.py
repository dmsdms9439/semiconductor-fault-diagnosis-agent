"""
[Area 6] 서비스 유용성 및 추론 속도 벤치마크 코드
- 목적: 데이터 입력부터 최종 진단까지의 전체 파이프라인 지연 시간(Latency)을 측정합니다.
- 주요 지표: Component-wise Latency (AE, LGBM, SHAP, RAG 소요 시간)
"""

import os
import sys
from datetime import datetime

# 프로젝트 루트 디렉토리를 sys.path에 추가하여 상위 디렉토리의 모듈을 임포트할 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import time
from inference import InferenceEngine
from shap_analysis import SHAPExplainer
from agents.rag_agent_v2 import GraphRAGAgentV2, shap_list_to_dict

def run_system_benchmark():
    print("🚀 [시스템 벤치마크] 단계별 처리 속도 측정을 시작합니다.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. 컴포넌트 초기화
    start_time = time.time()
    engine = InferenceEngine()
    explainer = SHAPExplainer(engine.lgb_model, engine.features)
    agent = GraphRAGAgentV2()
    init_time = time.time() - start_time
    print(f"⚙️  시스템 초기화 완료: {init_time:.2f}초")
    
    # 2. 테스트 샘플 선정
    test_path = 'data/test_tstr.csv'
    df = pd.read_csv(test_path)
    df.columns = df.columns.str.strip()
    sample = df.iloc[0].to_dict()
    
    # 3. 단계별 지연 시간 측정 (10회 반복 후 평균값 계산)
    latencies = []
    
    print(f"🔍 10회 반복 측정을 통해 평균 지연 시간을 산출합니다...")
    for i in range(10):
        step_times = {}
        
        # Step 1: Inference (AE + LGBM)
        t0 = time.time()
        result = engine.predict(sample)
        step_times['Inference'] = time.time() - t0
        
        # Step 2: SHAP Analysis
        t1 = time.time()
        sample_df = pd.DataFrame([sample])
        sample_df.columns = sample_df.columns.str.strip()
        X_scaled = engine.scaler.transform(sample_df[engine.features])
        pred_idx = 0 # 예시용
        shap_out = explainer.explain(X_scaled, sample, pred_idx)
        step_times['SHAP'] = time.time() - t1

        # Step 3: RAG Diagnosis (Neo4j 조회 + OpenAI 호출 포함)
        # server._call_rag_v2() 와 같은 경로: SHAP 결과를 지문 매칭에 넘긴다.
        t2 = time.time()
        _ = agent.recommend(
            shap_analysis=shap_list_to_dict(shap_out),
            fault_name_hint=result['status'].replace(" ", ""),
            question="이 이상 징후의 원인과 점검 절차를 알려주세요.",
        )
        step_times['RAG'] = time.time() - t2
        
        step_times['Total'] = sum(step_times.values())
        latencies.append(step_times)
    
    agent.close()

    latency_df = pd.DataFrame(latencies)
    avg_latency = latency_df.mean()
    
    # 4. 결과 출력 및 저장
    os.makedirs('validation/results', exist_ok=True)
    latency_df.to_csv(f'validation/results/latency_{timestamp}.csv', index=False)
    
    print(f"\n--- 시스템 성능 요약 (단위: 초) ---")
    print(f"1. 추론 엔진 (AE+LGBM): {avg_latency['Inference']:.4f}s")
    print(f"2. SHAP 분석:         {avg_latency['SHAP']:.4f}s")
    print(f"3. RAG 에이전트:       {avg_latency['RAG']:.4f}s (네트워크 속도 포함)")
    print(f"-----------------------------------")
    print(f"총 소요 시간 (Total):  {avg_latency['Total']:.4f}s")
    
    if avg_latency['Total'] < 2.0:
        print("\n✅ 성능 우수: 전체 처리 시간이 2초 미만으로 실시간 대응이 가능합니다.")
    else:
        print("\n⚠️ 성능 주의: LLM 답변 생성에서 지연이 발생하고 있습니다.")

    print(f"\n📋 상세 벤치마크 결과 저장 완료: validation/results/latency_{timestamp}.csv")

if __name__ == "__main__":
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ 에러: OpenAI API 키가 없어 RAG 측정이 불가능합니다.")
    else:
        run_system_benchmark()
