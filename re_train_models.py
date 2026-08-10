import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import recall_score
import lightgbm as lgb
import joblib
import json
import os
from inference import Autoencoder

def re_train_models():
    print("🚀 [재학습] 데이터 분포 정렬 및 모델 재학습을 시작합니다.")
    
    # 1. 데이터 및 Gap 정보 로드
    train_path = 'data/train_tstr.csv'
    gap_path = 'validation/results/gap_sensors.json'
    
    if not os.path.exists(train_path) or not os.path.exists(gap_path):
        print("❌ 필요한 파일(train_augmented.csv 또는 gap_sensors.json)이 없습니다.")
        return

    df = pd.read_csv(train_path)
    df.columns = df.columns.str.strip()  # [추가] 컬럼명 공백 제거
    
    with open(gap_path, 'r') as f:
        gap_info = json.load(f)
    # [추가] Gap 정보의 키(센서명) 공백 제거
    gap_info = {k.strip(): v for k, v in gap_info.items()}
    
    print(f"📋 학습 데이터 로드 완료 ({len(df)}건). Gap 센서 {len(gap_info)}개 발견.")

    # 2. [핵심] 데이터 분포 정렬 (Distribution Realignment)
    print(f"📊 {len(gap_info)}개 센서에 대해 데이터 정렬을 시작합니다...")
    for i, (sensor, stats) in enumerate(gap_info.items()):
        if sensor in df.columns:
            real_mean = stats['Real_Mean']
            real_std = stats['Real_Std']
            synth_mean = stats['Synth_Mean']
            synth_std = stats['Synth_Std']
            
            idx = df['Is_Synthetic'] == 1
            # 보정 공식 적용
            df.loc[idx, sensor] = (df.loc[idx, sensor] - synth_mean) * (real_std / (synth_std + 1e-9)) + real_mean
        
        if (i+1) % 20 == 0:
            print(f"   - {i+1}개 센서 정렬 완료...")
    
    print("✅ 데이터 분포 정렬 완료.")

    # 3. 전처리 (Scaling)
    print("🧹 데이터 전처리 중...")
    exclude = ['Time_Step', 'Time', 'Step Number', 'Run_Name', 'run_id', 'Fault_Name', 'Is_Synthetic', 'Synthesis_Method', 'Data_Type', 'TIME', 'Time.1', 'TIME.1']
    features = [c for c in df.columns if c not in exclude and df[c].dtype in ['float64', 'int64']]
    
    X = df[features].values
    y_labels = df['Fault_Name'].values
    
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    
    le = LabelEncoder()
    y_encoded = le.fit_transform(y_labels)
    
    # 4. 오토인코더(AE) 학습 (정상 데이터만 사용)
    X_normal = X_scaled[df['Fault_Name'] == 'Normal']
    X_train_tensor = torch.FloatTensor(X_normal)
    
    input_dim = X_train_tensor.shape[1]
    model_ae = Autoencoder(input_dim)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model_ae.parameters(), lr=0.001)
    
    print(f"🏋️  오토인코더 학습 시작 (데이터 수: {len(X_normal)})...")
    model_ae.train()
    for epoch in range(30): # 50 -> 30으로 조정하여 속도 확보
        optimizer.zero_grad()
        output = model_ae(X_train_tensor)
        loss = criterion(output, X_train_tensor)
        loss.backward()
        optimizer.step()
        if (epoch+1) % 10 == 0:
            print(f"   - Epoch [{epoch+1}/30], Loss: {loss.item():.6f}")
            
    # 5. 임계치(Threshold) 재설정 (Suspect Zone 고도화)
    model_ae.eval()
    with torch.no_grad():
        recon = model_ae(X_train_tensor)
        mse = torch.mean((X_train_tensor - recon)**2, dim=1).numpy()
        # [고도화] 다중 임계치 설정
        new_threshold = np.percentile(mse, 90) # 기존 90%
        suspect_threshold = np.percentile(mse, 70) # 의심 구역 70%
        print(f"🎯 임계치 설정 완료: Base {new_threshold:.6f}, Suspect {suspect_threshold:.6f}")

    # 6. LightGBM 학습
    print("🏋️  LightGBM 학습 시작 (Sklearn API)...")
    lgb_model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.1,
        objective='multiclass',
        random_state=42,
        is_unbalance=True,  # [추가] 클래스 불균형 해소
        verbose=-1
    )
    lgb_model.fit(X_scaled, y_encoded)

    # 7. 모델 및 상태 저장
    os.makedirs('models', exist_ok=True)
    # 모델 저장 시 suspect_threshold 추가
    torch.save({
        'model_state_dict': model_ae.state_dict(),
        'threshold': float(new_threshold),
        'suspect_threshold': float(suspect_threshold),
        'features': features
    }, 'models/autoencoder.pth')
    
    joblib.dump(scaler, 'models/scaler.joblib')
    joblib.dump(lgb_model, 'models/lightgbm_model.joblib')
    joblib.dump(le, 'models/label_encoder.joblib')
    
    print("💾 모든 모델 및 전처리기가 models/ 폴더에 저장되었습니다.")

if __name__ == "__main__":
    re_train_models()
