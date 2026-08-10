from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import os
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

if "OPEN_AI_API_KEY" in os.environ and "OPENAI_API_KEY" not in os.environ:
    os.environ["OPENAI_API_KEY"] = os.environ["OPEN_AI_API_KEY"]

try:
    from agents.llm_guard import ensure_openai_enabled
except ImportError:  # 이 파일을 스크립트로 직접 실행하는 경우
    from llm_guard import ensure_openai_enabled


class SHAPAgent:
    def __init__(self, model_name=None):
        ensure_openai_enabled()   # OPENAI_ENABLED=false 면 여기서 차단(과금 방지)
        model_name = model_name or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm = ChatOpenAI(model=model_name, temperature=0)
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert Semiconductor Process Engineer.
Your task is to analyze sensor data anomalies based on SHAP values and raw sensor statistics.

Context:
- Process: Plasma Etching
- You will receive a list of top sensors that contributed to a fault detection.
- Each sensor entry includes: Current Value, Mean (Normal), Normal Range, Status (High/Low), and SHAP Direction.

Guidelines:
1. Explain the physical impact of the sensor being 'High' or 'Low' for the specific fault.
2. Link the sensor status to potential equipment issues (e.g., "Pressure is High, suggesting a Throttle Valve or Vacuum Pump issue").
3. Use the SHAP direction to confirm if the sensor's current state is what primarily drove the AI's decision.
4. Output should be in Korean.
5. 리포트 서두에 '알려지지 않은 결함'이라는 표현을 쓰지 마십시오. 대신 '감지된 결함' 또는 단순히 '결함'이라는 표현을 사용하고, '결함에 대한 센서 분석 결과를 바탕으로 기술적 분석을 제공합니다'와 같은 정중하고 전문적인 문구로 시작하십시오."""),
            ("user", "Detected Fault: {fault_name}\nSensor Analysis Data:\n{analysis_json}\n\nPlease provide a deep technical analysis.")
        ])
        self.chain = self.prompt | self.llm | StrOutputParser()

    def explain_fault(self, fault_name, analysis_results):
        """
        analysis_results: list of dicts from SHAPExplainer.explain
        """
        # Convert list to a readable string for the LLM
        analysis_str = json.dumps(analysis_results, indent=2, ensure_ascii=False)
        
        try:
            explanation = self.chain.invoke({
                "fault_name": fault_name,
                "analysis_json": analysis_str
            })
            return explanation
        except Exception as e:
            return f"Error generating explanation: {str(e)}"

if __name__ == "__main__":
    agent = SHAPAgent()
    print("SHAPAgent updated.")
