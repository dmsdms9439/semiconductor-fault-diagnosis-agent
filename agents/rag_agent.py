"""
GraphRAG V1 — LEGACY. 새 코드에서는 쓰지 말 것.

이 에이전트의 Cypher 는 FIXED_BY · Task · Cause · AFFECTS_COMPONENT 관계를 요구하는데,
현행 지식그래프(graphdb/neo4j_loader_v2.py)는 CAUSED_BY · REMEDIATED_BY · DEGRADES 를
쓰는 v2 스키마다. 그래서 이 파일은 대부분의 결함에서 빈 컨텍스트를 반환한다.
get_context_from_graph() 의 WHERE 절에 결함명("Pressure", "TCP Top Pwr Fault")이
하드코딩돼 있어 일반화도 되지 않는다.

server.py 의 실행 경로(자동 Phase 2 · /api/rag_search)는 전부 GraphRAGAgentV2 로
통일되어 이 파일을 더 이상 부르지 않는다. 남아 있는 참조는 검증 스크립트 둘뿐이다.
  - validation/system_benchmark.py
  - validation/rag_assessment.py

신규 작업은 agents/rag_agent_v2.py 를 쓴다.
"""

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from agents.llm_guard import ensure_openai_enabled
except ImportError:  # 이 파일을 스크립트로 직접 실행하는 경우
    from llm_guard import ensure_openai_enabled


class GraphRAGAgent:
    def __init__(self, model_name=None):
        ensure_openai_enabled()   # OPENAI_ENABLED=false 면 여기서 차단(과금 방지)
        model_name = model_name or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm = ChatOpenAI(model=model_name, temperature=0)
        
        # Neo4j Driver
        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a Senior Semiconductor Maintenance Expert. 
Your goal is to provide specific troubleshooting recommendations and Standard Operating Procedures (SOPs) based on information retrieved from a Knowledge Graph and real-time sensor anomalies.

Knowledge Graph Context:
{context}

Real-time Sensor Anomalies (SHAP):
{shap_context}

Detected Fault: {fault_name}

Guidelines:
1. Combine the Knowledge Graph SOP with the specific sensor anomalies reported by SHAP.
2. If SHAP indicates a specific sensor is 'High' or 'Low', prioritize troubleshooting steps related to that sensor's subsystem.
3. Clearly identify which part is likely causing the issue and summarize the SOP steps.
4. Output should be in Korean."""),
            ("user", "What are the recommended countermeasures for the {fault_name}?")
        ])
        self.chain = self.prompt | self.llm | StrOutputParser()

    def close(self):
        self.driver.close()

    def get_context_from_graph(self, fault_name):
        """
        Retrieves Fault -> Part and Fault -> SOP relationships from Neo4j
        """
        query = """
        MATCH (f:Fault {name: $fault_name})
        OPTIONAL MATCH (f)<-[:DETECTS]-(task:Task)
        OPTIONAL MATCH (f)-[:FIXED_BY]->(sop:SOP)
        OPTIONAL MATCH (cause:Cause)-[:RECOMMENDED_ACTION]->(sop)
        OPTIONAL MATCH (cause)-[:AFFECTS_COMPONENT]->(comp:Component)
        OPTIONAL MATCH (vsm:VirtualSensorModel)-[:PREDICTS]->(ws:WaferState)-[:INDICATES]->(risk:FaultRisk)
        WHERE (f.name CONTAINS "Pressure" AND risk.name CONTAINS "Over Etch") OR f.name = "TCP Top Pwr Fault"
        
        RETURN 
            f.name as fault,
            sop.title as sop_title, 
            sop.steps as sop_steps,
            collect(DISTINCT comp.name) as components,
            cause.name as cause_name,
            ws.name as impacted_quality
        """
        with self.driver.session() as session:
            result = session.run(query, fault_name=fault_name)
            records = [dict(record) for record in result]
            
            if not records or not records[0]['sop_title']:
                return "No specific SOP found in the knowledge graph for this fault."
            
            context = ""
            for r in records:
                context += f"- Fault: {r['fault']}\n"
                context += f"- SOP Title: {r['sop_title']}\n"
                context += f"- SOP Steps: {r['sop_steps']}\n"
                if r['components']:
                    context += f"- Affected Components: {', '.join(r['components'])}\n"
                if r['cause_name']:
                    context += f"- Potential Cause: {r['cause_name']}\n"
                if r['impacted_quality']:
                    context += f"- Impacted Wafer Quality: {r['impacted_quality']}\n"
            return context

    def get_recommendation(self, fault_name, shap_analysis=None):
        # 1. Retrieve data from Neo4j
        context = self.get_context_from_graph(fault_name)
        
        # 2. Format SHAP context if available
        shap_context = "No real-time sensor analysis provided."
        if shap_analysis:
            import json
            shap_context = json.dumps(shap_analysis, indent=2, ensure_ascii=False)
            
        # 3. Generate response using LLM
        try:
            response = self.chain.invoke({
                "context": context,
                "shap_context": shap_context,
                "fault_name": fault_name
            })
            return response
        except Exception as e:
            return f"Error generating recommendation: {str(e)}"

if __name__ == "__main__":
    agent = GraphRAGAgent()
    try:
        # Test with an existing fault
        fault = "TCP Top Pwr Fault"
        print(f"--- Recommendation for {fault} ---")
        print(agent.get_recommendation(fault))
    finally:
        agent.close()
