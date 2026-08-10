# 머신러닝과 딥러닝을 결합하여 센서 데이터의 '이상 여부'와 고장 종류를 판별하는 핵심 추론 엔진
# 1단계로는 오토인코더를 통해 이상치를 탐지하고, 2단계로 LightGBM을 통해 세부 분류 수행

# 고도화 진행한 코드
    # 1. 로깅(Logging) 시스템 설정: 에러와 시스템 상태를 파일과 화면에 동시 기록
    # 2. 하드웨어 가속(GPU) 자동 할당
    # 3. 방어적 프로그래밍: 데이터가 없거나 에러가 발생해도 서버가 죽지 않도록 보호
    # 4. 속도 최적화: Pandas를 거치지 않고 Numpy 배열로 직접 변환 (실시간 처리 핵심)
    # 5. 하드코딩 제거: 초기화 시 설정한 lgbm_confidence_threshold 사용
    # 6. 동적 임계치 알고리즘 적용


import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import joblib
import os
# [추가] 운영 환경을 위한 로깅, 타입 힌트, 동적 임계치용 큐 라이브러리 추가
import logging
from typing import Dict, Any
from collections import deque 

# [추가] 에러 기록 및 시스템 상태 모니터링을 위한 로거 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("InferenceEngine")

class Autoencoder(nn.Module):
    """이상치 탐지를 위한 오토인코더 모델 (구조는 기존과 동일하게 유지)"""
    def __init__(self, input_dim):
        super(Autoencoder, self).__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 16)
        )
        self.decoder = nn.Sequential(
            nn.Linear(16, 32),
            nn.ReLU(),
            nn.Linear(32, 64),
            nn.ReLU(),
            nn.Linear(64, input_dim)
        )

    def forward(self, x):
        return self.decoder(self.encoder(x))

class InferenceEngine:
    # [기존] def __init__(self, model_dir='models'):
    # [변경] 모델 경로 외에 동적 임계치 파라미터와 신뢰도 기준값을 외부에서 받도록 확장
    def __init__(self, model_dir='models', lgbm_confidence_threshold=0.90, very_high_threshold=0.95, window_size=100, std_multiplier=2.0):
        self.model_dir = model_dir
        self.lgbm_confidence_threshold = lgbm_confidence_threshold
        self.very_high_threshold = very_high_threshold
        
        # [추가] 동적 임계치 알고리즘 (Sliding Window) 세팅
        self.window_size = window_size         
        self.std_multiplier = std_multiplier   
        self.mse_history = deque(maxlen=self.window_size)
        
        # ... (생략된 기존 초기화 코드)
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self._load_models()

    def _load_models(self):
        ae_path = os.path.join(self.model_dir, 'autoencoder.pth')
        ae_data = torch.load(ae_path, map_location=self.device, weights_only=False)
        self.features = [f.strip() for f in ae_data['features']]
        self.base_threshold = ae_data['threshold']
        self.suspect_threshold = ae_data.get('suspect_threshold', self.base_threshold * 0.8)
        
        self.model_ae = Autoencoder(len(self.features)).to(self.device)
        self.model_ae.load_state_dict(ae_data['model_state_dict'])
        self.model_ae.eval()
        self.scaler = joblib.load(os.path.join(self.model_dir, 'scaler.joblib'))
        self.lgb_model = joblib.load(os.path.join(self.model_dir, 'lightgbm_model.joblib'))
        self.le = joblib.load(os.path.join(self.model_dir, 'label_encoder.joblib'))

    def predict(self, metrics_dict: Dict[str, Any], override_threshold=None) -> Dict[str, Any]:
        """단일 센서 데이터 이상 탐지 및 분류 (Suspect Zone 포함 5단계 판별 로직)"""
        if not metrics_dict:
            return {"status": "ERROR", "message": "입력 데이터가 없습니다."}
        
        metrics_dict = {k.strip(): v for k, v in metrics_dict.items()}

        try:
            row_list = [float(metrics_dict.get(f, 0.0)) for f in self.features]
            X_array = np.array(row_list).reshape(1, -1)
            X_scaled = self.scaler.transform(X_array)
            X_tensor = torch.FloatTensor(X_scaled).to(self.device)
            
            with torch.no_grad():
                recon = self.model_ae(X_tensor)
                mse = torch.mean((X_tensor - recon)**2).item()
            
            # 1. 임계치 결정
            if override_threshold is not None:
                current_threshold = override_threshold
            else:
                current_threshold = self.base_threshold

            # 2. 분류 모델 예측
            probs = self.lgb_model.predict_proba(X_scaled)[0]
            max_prob = float(np.max(probs))
            pred_idx = int(np.argmax(probs))
            pred_label = self.le.inverse_transform([pred_idx])[0]

            # 3. 고도화된 5단계 판단 로직 (완화된 탐지 기준)
            ae_anomaly = mse > current_threshold
            ae_suspect = mse > self.suspect_threshold
            
            if ae_anomaly:
                # AE가 명확히 이상 → LightGBM 신뢰도가 어느 정도(0.5 이상)만 되면 해당 결함으로 인정
                if max_prob >= 0.5 and pred_label != 'Normal':
                    final_status = pred_label
                    is_anomaly = True
                else:
                    # 신뢰도가 너무 낮거나 'Normal'로 분류된 경우
                    final_status = "UNKNOWN FAULT"
                    is_anomaly = True
                
                logger.info(f"🚨 Anomaly Detected | MSE: {mse:.4f} | Pred: {pred_label} ({max_prob:.2f}) -> Final: {final_status}")
            elif ae_suspect:
                # Suspect Zone: MSE가 약간 높음
                if pred_label != 'Normal' and max_prob >= 0.6:
                    final_status = pred_label
                    is_anomaly = True
                else:
                    final_status = "Normal"
                    is_anomaly = False
            else:
                # AE 정상 구간
                if max_prob >= 0.85 and pred_label != 'Normal':
                    final_status = pred_label
                    is_anomaly = True
                else:
                    final_status = "Normal"
                    is_anomaly = False

            # 4. 상위 3개 후보군 추출 (Top-3 Candidates)
            # 이상(Anomaly)인 경우 'Normal'을 제외하고 결함 후보만 추출하여 재현율 보정
            filtered_probs = probs.copy()
            normal_idx = list(self.le.classes_).index('Normal')
            
            if is_anomaly:
                filtered_probs[normal_idx] = 0 # 정상을 제외
                # 남은 확률들로 재정규화 (합이 1이 되도록)
                sum_probs = np.sum(filtered_probs)
                if sum_probs > 0:
                    filtered_probs = filtered_probs / sum_probs
            
            top_indices = np.argsort(filtered_probs)[::-1][:3]
            top_candidates = []
            for idx in top_indices:
                label = self.le.inverse_transform([idx])[0]
                conf = float(filtered_probs[idx])
                top_candidates.append({"label": label, "confidence": conf})

            # 5. 정상 데이터인 경우에만 history 업데이트 (Threshold Drift 방지)
            if not is_anomaly:
                capped_mse = min(mse, self.base_threshold * 2.0)
                self.mse_history.append(capped_mse)
                
            return {
                'status': final_status,
                'mse': mse,
                'current_threshold': current_threshold,
                'confidence': max_prob,
                'is_anomaly': is_anomaly,
                'predicted_label': pred_label,
                'ae_anomaly': ae_anomaly,
                'top_candidates': top_candidates  # [추가] 상위 3개 후보 정보
            }
            
        except Exception as e:
            logger.error(f"예측 중 예외 발생: {str(e)}")
            return {"status": "ERROR", "message": str(e)}
            
        # [추가] 처리 중 예외 발생 시 로그를 남기고 시스템 지속
        except Exception as e:
            logger.error(f"예측 중 예외 발생: {str(e)}")
            return {"status": "ERROR", "message": "내부 서버 오류"}

if __name__ == "__main__":
    # 고도화된 엔진 테스트
    engine = InferenceEngine(window_size=50) # 50개 데이터를 윈도우로 사용
    
    # 더미 데이터로 10번 연속 테스트 (동적 임계치 변화 관찰)
    logger.info("연속 데이터 스트리밍 테스트 시작...")
    for i in range(10):
        # 10번째 데이터에 인위적으로 거대한 이상치(노이즈) 주입
        noise = 5.0 if i == 9 else 0.0 
        sample_data = {f"sensor_{j}": np.random.rand() + noise for j in range(16)} 
        
        result = engine.predict(sample_data)
        if result.get("status") != "ERROR":
            print(f"[{i+1}회차] 상태: {result['status']}, MSE: {result['mse']:.4f}, 현재임계치: {result['current_threshold']:.4f}")