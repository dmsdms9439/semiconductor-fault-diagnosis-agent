"""
[Area 1 & 2] 이상 탐지 및 결함 분류 성능 검증 코드
- 목적: 오토인코더(AE)의 이상 탐지 성능(Recall, Precision)과 LightGBM의 결함 분류 정확도를 검증합니다.
- 주요 지표: Recall, Precision, F1-Score, ROC-AUC, Confusion Matrix
"""

import pandas as pd
import numpy as np
from sklearn.metrics import (
    classification_report, confusion_matrix, accuracy_score, 
    f1_score, precision_score, recall_score, roc_auc_score
)
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys
from datetime import datetime

# 프로젝트 루트 디렉토리를 sys.path에 추가하여 상위 디렉토리의 모듈을 임포트할 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inference import InferenceEngine

def run_performance_assessment():
    print("🚀 [성능 검증] 이상 탐지 및 결함 분류 테스트를 시작합니다.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. 테스트 데이터 로드
    test_path = 'data/test_tstr.csv'
    if not os.path.exists(test_path):
        print(f"❌ 에러: {test_path} 파일을 찾을 수 없습니다.")
        return
    
    df = pd.read_csv(test_path)
    df.columns = df.columns.str.strip() # [추가] 컬럼명 공백 제거
    print(f"📋 총 {len(df)}개의 테스트 샘플을 로드했습니다.")
    
    # 2. 추론 엔진 초기화
    engine = InferenceEngine()
    is_dynamic = hasattr(engine, 'mse_history')
    print(f"⚙️  추론 엔진 모드: {'동적 임계치 적용 중' if is_dynamic else '고정 임계치 사용 중'}")
    
    # 3. 추론 수행 및 결과 수집
    y_true_anomaly = []     # 실제 이상 여부 (0: 정상, 1: 이상)
    y_pred_anomaly = []     # 예측 이상 여부
    y_true_label = []       # 실제 결함 라벨
    y_pred_label = []       # 예측 결함 라벨
    mse_scores = []         # AE가 계산한 복원 오차(MSE) 점수
    threshold_history = []  # 시간에 따른 임계치 변화 기록
    
    print("🔍 테스트 데이터에 대해 전수 조사를 실시합니다...")
    for _, row in df.iterrows():
        metrics = row.to_dict()
        true_label = metrics['Fault_Name']
        is_true_anomaly = (true_label != 'Normal')
        
        # 실제 추론 엔진 실행
        result = engine.predict(metrics)
        
        y_true_anomaly.append(int(is_true_anomaly))
        y_pred_anomaly.append(int(result['is_anomaly']))
        y_true_label.append(true_label)
        y_pred_label.append(result['status'])
        mse_scores.append(result['mse'])
        threshold_history.append(result.get('current_threshold', getattr(engine, 'threshold', 0)))
        
    # 4. [Area 1] 이상 탐지 성능 평가 (Autoencoder)
    print("\n--- [Area 1] 이상 탐지 성능 (AE) ---")
    recall = recall_score(y_true_anomaly, y_pred_anomaly)
    precision = precision_score(y_true_anomaly, y_pred_anomaly, zero_division=0)
    f1 = f1_score(y_true_anomaly, y_pred_anomaly, zero_division=0)
    
    print(f"재현율(Recall):    {recall:.4f} (실제 이상을 얼마나 잘 찾아냈는가)")
    print(f"정밀도(Precision): {precision:.4f} (이상이라고 한 것 중 실제 이상이 얼마나 있는가)")
    print(f"F1-Score:         {f1:.4f}")
    try:
        auc = roc_auc_score(y_true_anomaly, mse_scores)
        print(f"ROC-AUC:          {auc:.4f} (모델의 전반적인 변별력)")
    except:
        print("ROC-AUC:          측정 불가")
        
    # 5. [Area 2] 결함 분류 성능 평가 (LightGBM)
    print("\n--- [Area 2] 결함 분류 성능 (LGBM) ---")
    labels = sorted(list(set(y_true_label) | set(y_pred_label)))
    
    acc = accuracy_score(y_true_label, y_pred_label)
    f1_macro = f1_score(y_true_label, y_pred_label, average='macro', zero_division=0)
    
    print(f"전체 정확도(Accuracy): {acc:.4f}")
    print(f"Macro F1-Score:      {f1_macro:.4f} (클래스별 불균형을 고려한 평균 성능)")
    
    print("\n[상세 분류 리포트]")
    print(classification_report(y_true_label, y_pred_label, zero_division=0))
    
    # 6. 결과 시각화 및 저장
    os.makedirs('validation/results', exist_ok=True)
    
    # 혼동 행렬(Confusion Matrix) 그리기
    cm = confusion_matrix(y_true_label, y_pred_label, labels=labels)
    plt.figure(figsize=(12, 8))
    sns.heatmap(cm, annot=True, fmt='d', xticklabels=labels, yticklabels=labels, cmap='Blues')
    plt.title(f'Fault Classification Confusion Matrix ({timestamp})')
    plt.ylabel('Actual Fault')
    plt.xlabel('Predicted Fault')
    plt.savefig(f'validation/results/cm_{timestamp}.png')
    
    # MSE 및 임계치 변화 추이 차트
    plt.figure(figsize=(15, 5))
    plt.plot(mse_scores, label='MSE Score', alpha=0.6, color='blue')
    plt.plot(threshold_history, label='Dynamic Threshold', color='red', linestyle='--')
    plt.title(f'MSE vs Dynamic Threshold Trend ({timestamp})')
    plt.xlabel('Sample Index')
    plt.ylabel('Score')
    plt.legend()
    plt.savefig(f'validation/results/trend_{timestamp}.png')
    
    # 텍스트 리포트 파일 저장
    report_path = f'validation/results/report_{timestamp}.txt'
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(f"검증 일시: {timestamp}\n")
        f.write(f"동적 임계치 사용 여부: {is_dynamic}\n\n")
        f.write(f"[Area 1] 이상 탐지 성능\n")
        f.write(f"- Recall: {recall:.4f}\n- Precision: {precision:.4f}\n- F1: {f1:.4f}\n\n")
        f.write(f"[Area 2] 결함 분류 성능\n")
        f.write(f"- Accuracy: {acc:.4f}\n- Macro F1: {f1_macro:.4f}\n")
        f.write("\n[상세 분류 결과]\n")
        f.write(classification_report(y_true_label, y_pred_label, zero_division=0))

    print(f"\n📊 검증 결과가 저장되었습니다:")
    print(f"   - 텍스트 리포트: {report_path}")
    print(f"   - 혼동 행렬 차트: validation/results/cm_{timestamp}.png")
    print(f"   - 오차 추이 차트: validation/results/trend_{timestamp}.png")
    
if __name__ == "__main__":
    run_performance_assessment()
