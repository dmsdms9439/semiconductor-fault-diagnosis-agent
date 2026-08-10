"""
[Area 3] 데이터 증강 품질 및 실제 데이터와의 유사도 검증 코드
- 목적: 증강(Augmented)된 데이터가 실제 정상 데이터의 통계적 특성을 얼마나 잘 유지하고 있는지 검증합니다.
- 주요 지표: 각 센서별 평균(Mean), 표준편차(Std), 분포의 유사성
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os
import os
import sys

# 프로젝트 루트 디렉토리를 sys.path에 추가하여 상위 디렉토리의 모듈을 임포트할 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

def run_data_quality_assessment():
    print("🚀 [데이터 품질 검증] 증강 데이터와 실제 데이터의 분포 비교를 시작합니다.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # [변경] TSTR 전략을 위해 Train(Synthetic)과 Test(Real) 파일을 직접 비교합니다.
    train_path = 'data/train_tstr.csv'
    test_path = 'data/test_tstr.csv'
    
    if not os.path.exists(train_path) or not os.path.exists(test_path):
        print(f"❌ 에러: {train_path} 또는 {test_path} 파일을 찾을 수 없습니다.")
        return
    
    train_df = pd.read_csv(train_path)
    test_df = pd.read_csv(test_path)
    
    train_df.columns = train_df.columns.str.strip()
    test_df.columns = test_df.columns.str.strip()
    
    # Train은 모두 Synthetic, Test는 모두 Real입니다.
    real_df = test_df[test_df['Fault_Name'] == 'Normal']
    synth_df = train_df[train_df['Fault_Name'] == 'Normal']
    
    print(f"📋 실제 데이터: {len(real_df)}건, 증강 데이터: {len(synth_df)}건")
    
    # 2. 분포 비교
    exclude = ['Time_Step', 'Time', 'Step Number', 'Run_Name', 'run_id', 'Fault_Name', 'Is_Synthetic', 'Synthesis_Method', 'Data_Type', 'TIME', 'Time.1', 'TIME.1']
    sensors = [c for c in train_df.columns if c not in exclude and train_df[c].dtype in ['float64', 'int64']]
    
    # 3. 통계적 유사도 계산 (평균 및 표준편차 차이)
    stats_comparison = []
    
    for s in sensors:
        real_mean, real_std = real_df[s].mean(), real_df[s].std()
        
        if not synth_df.empty:
            synth_mean, synth_std = synth_df[s].mean(), synth_df[s].std()
            mean_diff = abs(real_mean - synth_mean) / (real_mean + 1e-9) * 100
            std_diff = abs(real_std - synth_std) / (real_std + 1e-9) * 100
        else:
            synth_mean, synth_std, mean_diff, std_diff = 0, 0, 0, 0
            
        stats_comparison.append({
            'Sensor': s,
            'Real_Mean': real_mean,
            'Synth_Mean': synth_mean,
            'Mean_Diff(%)': mean_diff,
            'Real_Std': real_std,
            'Synth_Std': synth_std,
            'Std_Diff(%)': std_diff
        })
    
    comp_df = pd.DataFrame(stats_comparison)
    
    # 4. 결과 저장 및 시각화
    os.makedirs('validation/results', exist_ok=True)
    
    # 상위 5개 센서의 분포 시각화 비교
    if not synth_df.empty:
        top_sensors = sensors[:5]
        plt.figure(figsize=(20, 10))
        for i, s in enumerate(top_sensors):
            plt.subplot(2, 3, i+1)
            sns.kdeplot(real_df[s], label='Real', fill=True, color='blue')
            sns.kdeplot(synth_df[s], label='Synthetic', fill=True, color='orange')
            plt.title(f'Distribution Comparison: {s}')
            plt.legend()
        
        plt.tight_layout()
        plt.savefig(f'validation/results/data_dist_{timestamp}.png')
        print(f"📊 분포 비교 차트 저장 완료: validation/results/data_dist_{timestamp}.png")
    
    # 통계 요약 저장
    comp_df.to_csv(f'validation/results/data_stats_{timestamp}.csv', index=False)
    print(f"📋 센서별 통계 비교 결과 저장 완료: validation/results/data_stats_{timestamp}.csv")
    
    # [추가] 고도화 작업을 위한 Gap Sensors 추출 (오차 5% 초과 센서)
    gap_threshold = 5.0
    gap_sensors_df = comp_df[(comp_df['Mean_Diff(%)'] > gap_threshold) | (comp_df['Std_Diff(%)'] > gap_threshold)]
    gap_sensors_json = gap_sensors_df.set_index('Sensor').to_json(orient='index')
    
    with open('validation/results/gap_sensors.json', 'w') as f:
        f.write(gap_sensors_json)
    
    # 요약 출력
    avg_mean_diff = comp_df['Mean_Diff(%)'].mean()
    print(f"\n--- 데이터 품질 요약 ---")
    print(f"평균값 오차(Avg Mean Diff): {avg_mean_diff:.2f}%")
    print(f"Gap 센서 개수 (>5%): {len(gap_sensors_df)}개")
    
    if avg_mean_diff < 5:
        print("✅ 품질 양호: 증강 데이터가 실제 데이터의 평균을 잘 따르고 있습니다.")
    else:
        print("⚠️ 품질 주의: 증강 데이터의 분포가 실제와 다소 차이가 있습니다.")
    
    print(f"📋 Gap 센서 리스트가 저장되었습니다: validation/results/gap_sensors.json")

if __name__ == "__main__":
    run_data_quality_assessment()
