"""
[Area 5] Agent/RAG 답변의 정확도 및 Retrieval 성능 검증 코드
- 목적: 결함 발생 시 RAG 시스템이 관련 매뉴얼을 정확히 검색(Retrieval)하고, 답변을 충실히 생성하는지 검증합니다.
- 주요 지표: Retrieval Hit Rate (관련 결함 키워드가 포함된 문서를 찾았는가?)
"""

import pandas as pd
import os
import sys

# 프로젝트 루트 디렉토리를 sys.path에 추가하여 상위 디렉토리의 모듈을 임포트할 수 있게 함
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.rag_agent import GraphRAGAgent
from datetime import datetime

def run_rag_assessment():
    print("🚀 [RAG 검증] 지식 검색 및 답변 생성 테스트를 시작합니다.")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. RAG 에이전트 초기화
    agent = GraphRAGAgent()
    
    # 2. 테스트 케이스 (다양한 결함 시나리오)
    test_cases = [
        "TCP Top Pwr Fault",
        "Pr +3 mTorr Fault",
        "RF -12 Watts Fault",
        "He Chuck Press Fault"
    ]
    
    results = []
    
    # 3. 각 케이스별 검색 및 답변 생성 수행
    print(f"🔍 {len(test_cases)}개의 결함 시나리오에 대해 지식 검색 성능을 측정합니다...")
    for fault in test_cases:
        # RAG 검색 수행 (내부적으로 context를 가져옴)
        # 실제 GraphRAGAgent의 구조에 따라 다르지만, 여기서는 답변 생성 프로세스를 통해 간접 측정
        response = agent.run(fault, shap_context="센서 데이터 이상 감지됨")
        
        # 검색된 내용에 해당 결함 키워드가 포함되어 있는지 체크 (Hit Rate)
        # agent.run() 결과물 내에 관련 키워드가 있는지 확인
        hit = any(kw.lower() in response.lower() for kw in fault.split(' '))
        
        results.append({
            'Fault_Case': fault,
            'Hit': hit,
            'Response_Length': len(response),
            'Response_Snippet': response[:100].replace('\n', ' ') + "..."
        })
    
    res_df = pd.DataFrame(results)
    
    # 4. 결과 출력 및 저장
    os.makedirs('validation/results', exist_ok=True)
    res_df.to_csv(f'validation/results/rag_eval_{timestamp}.csv', index=False)
    
    hit_rate = res_df['Hit'].mean() * 100
    print(f"\n--- RAG 검증 요약 ---")
    print(f"전체 검색 성공률(Hit Rate): {hit_rate:.1f}%")
    print(res_df[['Fault_Case', 'Hit', 'Response_Length']])
    
    print(f"\n📋 상세 결과 저장 완료: validation/results/rag_eval_{timestamp}.csv")

if __name__ == "__main__":
    # API 키 확인 (RAG 에이전트 실행에 필요)
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ 에러: OPENAI_API_KEY 환경 변수가 설정되어 있지 않습니다.")
    else:
        run_rag_assessment()
