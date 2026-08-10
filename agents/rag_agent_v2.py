"""
GraphRAG Agent v2 — Two-stage retrieval + SHAP fingerprint matching

Token optimization techniques (estimated 40-60 percent saving vs naive JSON injection):
  1. SHAP context: JSON dump -> compact natural-language line (~25 vs ~120 tokens)
  2. SOP: abstract first, full steps fetched only on follow-up (~70 vs ~400 tokens)
  3. Cypher returns trimmed property set, not whole node dicts
  4. System prompt: 4-bullet guideline -> 2-line role + format directive

Retrieval design (paper-grounded):
  Stage 1 (Coarse):
     SHAP top-k sensors -> match against Fault.sensors_low/high fingerprints
     -> rank candidate Faults by overlap score
     -> aggregate up to FaultCategory if no single fault dominates
  Stage 2 (Fine, only if user asks for detail):
     For top-1 fault, traverse Fault -> Mechanism -> Component -> SOP (abstract)
     Full SOPStep fetch only on explicit user request

References:
  - Wise 1999 fault catalog -> fingerprint matching
  - Sofge 1997 g_model -> wafer-state risk signals
  - Microsoft GraphRAG (Edge et al. 2024) -> coarse-to-fine pattern
"""

import os
from typing import Optional, Dict, List, Any, Tuple
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()


# ------------------------------------------------------------------
# SHAP -> compact natural language (token saver #1)
# ------------------------------------------------------------------
def compact_shap(shap_analysis: Optional[Dict[str, Any]]) -> str:
    """
    Convert SHAP dict into a single short line.

    Input:
      {"He_Pressure":   {"value": -2.3, "direction": "Low",  "rank": 1},
       "TCP_Top_Power": {"value":  1.8, "direction": "High", "rank": 2}}
    Output:
      "Top SHAP deviations: He Pressure (Low, -2.3, rank 1); TCP Top Power (High, +1.8, rank 2)"
    """
    if not shap_analysis:
        return "No SHAP analysis provided."
    ranked = sorted(shap_analysis.items(),
                    key=lambda kv: kv[1].get("rank", 99))
    parts = []
    for sensor, info in ranked[:5]:  # cap at top-5; Sofge showed >5 vars degrade models
        direction = info.get("direction", "?")
        value = info.get("value", 0.0)
        rank = info.get("rank", "?")
        sign = "+" if value >= 0 else ""
        parts.append(f"{sensor} ({direction}, {sign}{value:.2f}, rank {rank})")
    return "Top SHAP deviations: " + "; ".join(parts)


# ------------------------------------------------------------------
# 센서명 정규화 (모델/SHAP 이름 -> KG Sensor.name)
# ------------------------------------------------------------------
# data/MACHINE_integrated.csv 의 MSS 센서 19개와 graphdb/neo4j_loader_v2.py 의
# mss_sensors 19개는 순서까지 1:1 로 대응한다. 그중 이름이 다른 10개만 적는다.
# 나머지 9개(BCl3 Flow, Cl2 Flow, RF Tuner, RF Load, RF Impedance, TCP Tuner,
# TCP Impedance, TCP Load, Vat Valve)는 양쪽이 같은 이름이라 alias 가 필요 없다.
#
# OES(파장값 '364.33')와 RFM(S2P4 등)은 KG 에 대응 노드가 없어 매핑하지 않는다.
# 정규화를 그대로 통과하고, 지문에 없으므로 매칭에서 자연히 탈락한다.
SENSOR_ALIASES = {
    "RF Btm Pwr":     "RF Bottom Power",
    "RF Btm Rfl Pwr": "RFB Reflected Power",
    "Endpt A":        "Endpoint A Detector",
    "He Press":       "Helium Pressure",
    "Pressure":       "Chamber Pressure",
    "RF Phase Err":   "Phase Error",
    "RF Pwr":         "RF Power",
    "TCP Phase Err":  "TCP Phase Error",
    "TCP Top Pwr":    "TCP Top Power",
    "TCP Rfl Pwr":    "TCP Reflected Power",
}


def normalize_sensor_name(name: str) -> str:
    """모델/SHAP 센서명을 KG canonical 이름으로. 대응이 없으면 원본 그대로 돌려준다."""
    if not name:
        return ""
    stripped = str(name).strip()
    return SENSOR_ALIASES.get(stripped, stripped)


def parse_shap_to_lists(shap_analysis: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    """Split SHAP into (low_sensors, high_sensors) for Cypher matching.

    센서 이름을 두 단계로 정리한다.
      1) 언더스코어 -> 공백   (기존 호출부가 'He_Pressure' 형태로 넣는 경우)
      2) SENSOR_ALIASES 치환  ('TCP Top Pwr' -> 'TCP Top Power')
    이 정규화가 없으면 stage1 Cypher 의 `s IN $high` 비교가 전부 빗나간다.
    """
    low, high = [], []
    if not shap_analysis:
        return low, high
    for raw_name, info in shap_analysis.items():
        sensor_name = normalize_sensor_name(raw_name.replace("_", " "))
        d = info.get("direction", "").lower()
        if d == "low":
            low.append(sensor_name)
        elif d == "high":
            high.append(sensor_name)
    return low, high


def shap_list_to_dict(analysis_results: Optional[List[Dict[str, Any]]],
                      top_k: int = 5) -> Dict[str, Any]:
    """SHAPExplainer.explain() 의 list 출력을 V2 가 받는 dict 로 변환.

    SHAPExplainer 의 반환 구조는 프론트엔드(App.jsx)와 Slack(_format_shap_lines)도
    함께 쓰므로 바꾸지 않고, V2 경계인 여기서만 형식을 맞춘다.

    입력 한 항목:  {"sensor": "TCP Top Pwr", "shap_value": 1.8, "status": "High", ...}
    출력:          {"TCP Top Pwr": {"value": 1.8, "direction": "High", "rank": 1}}

    direction 에는 SHAPExplainer 의 'direction'(Positive/Negative Influence)이 아니라
    'status'(High/Low/Normal)를 넣는다. 지문 매칭이 필요로 하는 것은 SHAP 부호가
    아니라 센서값이 정상범위 대비 높은지 낮은지이기 때문이다.
    """
    out: Dict[str, Any] = {}
    if not analysis_results:
        return out
    for rank, item in enumerate(analysis_results[:top_k], 1):
        if not isinstance(item, dict):
            continue
        sensor = item.get("sensor")
        if not sensor:
            continue
        out[sensor] = {
            "value": float(item.get("shap_value", 0.0)),
            "direction": item.get("status", "Normal"),
            "rank": rank,
        }
    return out


# 개념어/한글 → 결함 코드 프리픽스 매핑 (자연어 검색 보조).
# KG의 Fault 이름은 영어 코드(TCP+20, Pr-2, He Chuck 등)라 한글/개념어는 이 표로 확장한다.
_CONCEPT_SYNONYMS = {
    "압력": ["Pr"], "pressure": ["Pr"],
    "파워": ["TCP", "RF"], "power": ["TCP", "RF"], "전력": ["TCP", "RF"],
    "소스": ["TCP"], "바이어스": ["RF"], "알에프": ["RF"],
    "헬륨": ["He"], "helium": ["He"], "척": ["He"], "chuck": ["He"],
    "염소": ["Cl2"], "chlorine": ["Cl2"],
    "붕소": ["BCl3"], "삼염화붕소": ["BCl3"],
}


try:
    from agents.llm_guard import ensure_openai_enabled
except ImportError:  # 이 파일을 스크립트로 직접 실행하는 경우
    from llm_guard import ensure_openai_enabled


class GraphRAGAgentV2:
    def __init__(self, model_name: str = None):
        ensure_openai_enabled()   # OPENAI_ENABLED=false 면 여기서 차단(과금 방지)
        # 비용/일관성 위해 다른 에이전트와 동일하게 LLM_MODEL(기본 gpt-4o-mini) 사용.
        model_name = model_name or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm = ChatOpenAI(model=model_name, temperature=0)

        uri = os.getenv("NEO4J_URI")
        user = os.getenv("NEO4J_USERNAME")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

        # Slim system prompt — guidelines compressed.
        self.prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a senior semiconductor maintenance expert for the Lam 9600 metal etcher. "
             "Use the retrieved Knowledge Graph context and SHAP signals to answer in Korean. "
             "Output format: (1) most likely fault and confidence, (2) root cause mechanism, "
             "(3) recommended SOP (title + abstract), (4) the 2-3 most relevant steps. "
             "Cite the KG reference field where present. Be concise."),
            ("user",
             "Detected fault candidate: {fault_name}\n"
             "{shap_line}\n\n"
             "Knowledge Graph context:\n{kg_context}\n\n"
             "Question: {question}")
        ])
        self.chain = self.prompt | self.llm | StrOutputParser()

    def close(self):
        self.driver.close()

    # ------------------------------------------------------------------
    # Stage 1 — fingerprint matching
    # ------------------------------------------------------------------
    def stage1_match_fault(self, shap_analysis: Dict[str, Any],
                           top_n: int = 3) -> List[Dict]:
        low, high = parse_shap_to_lists(shap_analysis)
        if not low and not high:
            return []

        query = """
        MATCH (f:Fault)
        WITH f,
             size([s IN f.sensors_low  WHERE s IN $low ]) AS low_hits,
             size([s IN f.sensors_high WHERE s IN $high]) AS high_hits,
             size(f.sensors_low) + size(f.sensors_high)   AS fp_size
        WITH f, low_hits + high_hits AS hits, fp_size
        WHERE hits > 0
        WITH f, hits, fp_size,
             toFloat(hits) /
               CASE fp_size WHEN 0 THEN 1 ELSE fp_size END AS score
        OPTIONAL MATCH (f)-[:BELONGS_TO]->(cat:FaultCategory)
        RETURN f.fault_id    AS fault_id,
               f.name        AS name,
               f.induced_via AS induced_via,
               f.region      AS region,
               cat.name      AS category,
               score, hits
        ORDER BY score DESC, hits DESC
        LIMIT $top_n
        """
        with self.driver.session() as session:
            result = session.run(query, low=low, high=high, top_n=top_n)
            return [dict(r) for r in result]

    # ------------------------------------------------------------------
    # Stage 2 — causal chain + SOP abstract (no steps yet)
    # ------------------------------------------------------------------
    def stage2_fetch_chain(self, fault_id: str) -> Dict:
        query = """
        MATCH (f:Fault {fault_id:$fid})
        OPTIONAL MATCH (f)-[:CAUSED_BY]->(m:Mechanism)
        OPTIONAL MATCH (m)-[:DEGRADES]->(c:Component)
        OPTIONAL MATCH (m)-[:REMEDIATED_BY]->(sop:SOP)
        RETURN f.name      AS fault_name,
               f.region    AS region,
               f.reference AS fault_ref,
               collect(DISTINCT {
                 mechanism: m.name,
                 timescale: m.timescale,
                 symptom: m.symptom,
                 reference: m.reference
               }) AS mechanisms,
               collect(DISTINCT c.name) AS components,
               collect(DISTINCT {
                 sop_id: sop.sop_id,
                 title: sop.title,
                 abstract: sop.abstract,
                 reference: sop.reference
               }) AS sops
        """
        with self.driver.session() as session:
            result = session.run(query, fid=fault_id).single()
            if not result:
                return {}
            return dict(result)

    def fetch_sop_steps(self, sop_id: str) -> List[Dict]:
        """Expensive: only call when user asks for full procedure."""
        query = """
        MATCH (s:SOP {sop_id:$sop_id})-[:HAS_STEP]->(st:SOPStep)
        RETURN st.step_no AS step_no, st.text AS text
        ORDER BY st.step_no
        """
        with self.driver.session() as session:
            return [dict(r) for r in session.run(query, sop_id=sop_id)]

    # ------------------------------------------------------------------
    # Format chain to compact context (token saver #2)
    # ------------------------------------------------------------------
    @staticmethod
    def _format_chain(chain: Dict) -> str:
        if not chain:
            return "No causal chain found."
        lines = [
            f"Fault: {chain.get('fault_name','?')} "
            f"(region: {chain.get('region','?')}, ref: {chain.get('fault_ref','?')})"
        ]
        mechs = [m for m in chain.get("mechanisms", []) if m.get("mechanism")]
        if mechs:
            lines.append("Mechanisms:")
            for m in mechs:
                lines.append(
                    f"  - {m['mechanism']} "
                    f"(timescale: {m.get('timescale','?')}; "
                    f"symptom: {m.get('symptom','?')})"
                )
        comps = [c for c in chain.get("components", []) if c]
        if comps:
            lines.append(f"Affected components: {', '.join(comps)}")
        sops = [s for s in chain.get("sops", []) if s.get("sop_id")]
        if sops:
            lines.append("Recommended SOPs:")
            for s in sops:
                lines.append(f"  - [{s['sop_id']}] {s['title']}: {s['abstract']}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def _match_by_text(self, text: str) -> List[Dict]:
        """자연어 질문/힌트에서 결함 이름 매칭.

        0) 공백 제거 후 이름 정확 일치 → 1) 전체 문자열 CONTAINS → 2) 토큰(길이 2+)별 매칭.

        0단계가 필요한 이유: KG 의 Fault.name 에는 공백이 없다('BCl3-5', 'TCP+30').
        사용자가 'BCl3 -5' 처럼 수치까지 적어 넣으면 1단계 CONTAINS 가 빗나가고,
        토큰 폴백이 'BCl3' 로 매칭한 뒤 ORDER BY f.name LIMIT 1 을 적용해
        이름순 첫 번째인 'BCl3+10' 을 돌려준다. 수치를 명시했으면 그 결함을 준다.
        수치 없이 'BCl3' 만 적었다면 기존대로 변형 중 아무거나 나온다.
        """
        import re
        compact = re.sub(r"\s+", "", text or "")
        with self.driver.session() as session:
            if compact:
                rec = session.run(
                    "MATCH (f:Fault) WHERE toLower(f.name) = toLower($name) "
                    "RETURN f.fault_id AS fault_id, f.name AS name LIMIT 1",
                    name=compact
                ).single()
                if rec:
                    return [{"fault_id": rec["fault_id"], "name": rec["name"], "score": 0.0}]

            rec = session.run(
                "MATCH (f:Fault) WHERE f.name CONTAINS $name "
                "RETURN f.fault_id AS fault_id, f.name AS name ORDER BY f.name LIMIT 1",
                name=text
            ).single()
            if rec:
                return [{"fault_id": rec["fault_id"], "name": rec["name"], "score": 0.0}]
            tokens = [t for t in re.split(r"[\s?!.,'\"()]+", text) if len(t) >= 2]
            # 한글/개념어 → 결함 코드 확장 (압력→Pr, 파워→TCP/RF 등)
            low = text.lower()
            for key, codes in _CONCEPT_SYNONYMS.items():
                if key in low:
                    tokens.extend(codes)
            tokens = list(dict.fromkeys(tokens))  # 중복 제거(순서 유지)
            if tokens:
                rec = session.run(
                    "MATCH (f:Fault) WHERE any(tok IN $tokens WHERE f.name CONTAINS tok) "
                    "RETURN f.fault_id AS fault_id, f.name AS name ORDER BY f.name LIMIT 1",
                    tokens=tokens
                ).single()
                if rec:
                    return [{"fault_id": rec["fault_id"], "name": rec["name"], "score": 0.0}]
        return []

    def recommend(self,
                  shap_analysis: Optional[Dict[str, Any]] = None,
                  fault_name_hint: Optional[str] = None,
                  question: str = "What is the recommended countermeasure?",
                  include_full_steps: bool = False) -> Dict:
        """
        Returns:
            'candidates'      : stage-1 ranking
            'chain'           : stage-2 causal chain for top-1
            'answer'          : LLM final text
            'token_estimate'  : rough context token count
        """
        # Stage 1 (SHAP 지문 매칭)
        candidates = self.stage1_match_fault(shap_analysis or {}, top_n=3)
        # Fallback: SHAP가 없거나(수동 검색) 매칭 실패 시 텍스트로 이름 매칭
        if not candidates and fault_name_hint:
            candidates = self._match_by_text(fault_name_hint)

        if not candidates:
            # 실패 원인별로 정확한 안내 (수동 경로는 SHAP를 쓰지 않음)
            low, high = parse_shap_to_lists(shap_analysis or {})
            if low or high:
                msg = "SHAP 지문에 매칭되는 결함이 KG에 없습니다. 센서 이름 정규화를 확인하세요."
            else:
                msg = ("입력한 검색어와 매칭되는 결함이 KG에 없습니다. "
                       "짧은 키워드(RF, TCP, He, Pressure 등)로 시도해 보세요.")
            return {"candidates": [], "chain": {}, "answer": msg, "token_estimate": 0}

        # Stage 2 for top-1
        top = candidates[0]
        chain = self.stage2_fetch_chain(top["fault_id"])

        full_steps_text = ""
        if include_full_steps and chain.get("sops"):
            sop_id = chain["sops"][0]["sop_id"]
            steps = self.fetch_sop_steps(sop_id)
            full_steps_text = "\n\nFull SOP steps:\n" + "\n".join(
                f"  {s['step_no']}. {s['text']}" for s in steps
            )

        kg_context = self._format_chain(chain) + full_steps_text
        shap_line = compact_shap(shap_analysis)
        token_estimate = (len(kg_context) + len(shap_line)) // 4

        try:
            answer = self.chain.invoke({
                "fault_name": top["name"],
                "shap_line": shap_line,
                "kg_context": kg_context,
                "question": question,
            })
        except Exception as e:
            answer = f"LLM error: {e}"

        return {
            "candidates": candidates,
            "chain": chain,
            "answer": answer,
            "token_estimate": token_estimate,
        }


# ------------------------------------------------------------------
# Demo
# ------------------------------------------------------------------
if __name__ == "__main__":
    agent = GraphRAGAgentV2(model_name="gpt-4o-mini")
    try:
        # Wise 1999 Fault #9 (He Chuck) pattern
        shap = {
            "Helium_Pressure":  {"value": -2.8, "direction": "Low",  "rank": 1},
            "Chamber_Pressure": {"value":  0.4, "direction": "High", "rank": 2},
        }
        out = agent.recommend(
            shap_analysis=shap,
            question="이 이상 징후의 원인과 점검 절차를 알려주세요."
        )
        print("=" * 60)
        print("Stage-1 candidates:")
        for c in out["candidates"]:
            print(f"  {c['fault_id']} {c['name']:15s} "
                  f"score={c['score']:.2f} cat={c.get('category')}")
        print(f"\nContext tokens (est): {out['token_estimate']}")
        print("\nLLM answer:\n")
        print(out["answer"])
    finally:
        agent.close()
