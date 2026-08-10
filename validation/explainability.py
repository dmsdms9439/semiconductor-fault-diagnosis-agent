"""
[Area 4] SHAP 설명의 일관성 및 물리적 타당성 검증 코드
- 목적: 모델이 내린 판단 근거(SHAP Value)가 실제 공정 지식과 일치하는지 검증합니다.
- 방법: 특정 결함 시나리오에서 중요하게 작용해야 하는 센서들이 실제로 SHAP 상위권에 등장하는지 확인합니다.
"""

import pandas as pd
import numpy as np
import os
import sys

# 프로젝트 루트 디렉토리를 sys.path에 추가하여 상위 디렉토리의 모듈을 임포트할 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference import InferenceEngine
from shap_analysis import SHAPExplainer
from datetime import datetime

def run_explainability_assessment():
    print("🚀 [설명 가능성 검증] SHAP 분석 결과의 타당성 조사를 시작합니다.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. 엔진 및 설명기 초기화
    engine = InferenceEngine()
    explainer = SHAPExplainer(engine.lgb_model, engine.features)
    
    # 2. 검증용 케이스 로드 (결함이 확실한 데이터 위주로 선택)
    test_path = 'data/test_tstr.csv'
    df = pd.read_csv(test_path)
    df.columns = df.columns.str.strip() # [추가] 컬럼명 공백 제거
    fault_samples = df[df['Fault_Name'] != 'Normal'].head(10) # 상위 10개 결함 샘플
    
    if fault_samples.empty:
        print("⚠️ 검증할 결함 샘플이 없습니다.")
        return

    results = []
    
    # 3. 각 결함별 SHAP 분석 수행 및 일관성 체크
    print(f"🔍 {len(fault_samples)}개의 결함 샘플에 대해 SHAP 일관성을 체크합니다...")
    for _, row in fault_samples.iterrows():
        metrics = row.to_dict()
        actual_fault = metrics['Fault_Name']
        
        # 모델 예측
        pred_res = engine.predict(metrics)
        pred_label = pred_res['status']
        
        # SHAP 설명 생성
        # InferenceEngine의 scaler와 features를 활용
        m_df = pd.DataFrame([metrics])
        m_df.columns = m_df.columns.str.strip()
        X_scaled = engine.scaler.transform(m_df[engine.features])
        pred_idx = list(engine.le.classes_).index(pred_label) if pred_label in engine.le.classes_ else 0
        
        shap_data = explainer.explain(X_scaled, metrics, pred_idx)
        
        # 상위 3개 중요 센서 추출
        top_3_sensors = [item['sensor'] for item in shap_data[:3]]
        
        results.append({
            'Actual': actual_fault,
            'Predicted': pred_label,
            'Top_1_Sensor': top_3_sensors[0] if len(top_3_sensors) > 0 else 'N/A',
            'Top_2_Sensor': top_3_sensors[1] if len(top_3_sensors) > 1 else 'N/A',
            'Top_3_Sensor': top_3_sensors[2] if len(top_3_sensors) > 2 else 'N/A'
        })
    
    res_df = pd.DataFrame(results)
    
    # 4. 결과 저장
    os.makedirs('validation/results', exist_ok=True)
    res_df.to_csv(f'validation/results/shap_consistency_{timestamp}.csv', index=False)
    
    print(f"\n--- SHAP 검증 요약 ---")
    print(res_df)
    print(f"\n📋 상세 결과 저장 완료: validation/results/shap_consistency_{timestamp}.csv")
    
    # 물리적 타당성 간이 체크 (예: Pressure 결함일 때 Pressure 센서가 포함되는가?)
    # 실제 도메인 지식 맵이 필요하지만, 여기서는 키워드 매칭으로 예시를 보여줌
    valid_count = 0
    for _, res in res_df.iterrows():
        if res['Actual'].split(' ')[0].lower() in res['Top_1_Sensor'].lower():
            valid_count += 1
            
    print(f"\n✅ 물리적 키워드 일치율: {valid_count/len(res_df)*100:.1f}% (샘플 내 기준)")

if __name__ == "__main__":
    run_explainability_assessment()
