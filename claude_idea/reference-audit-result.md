# 근거 참조 전수 대조 결과 (2026-08-10)

대상: `README.md`, `claude_idea/agent-architecture.html`(구 `agent-architecture-onepager.html`)
방법: 문서에 적힌 모든 `파일:라인` 참조를 실제 소스와 1:1 대조.

**결과: 참조 45개 중 43개 정확, 2개 어긋남.** 어긋난 2개는 교정 완료.
표기법은 사용자 결정에 따라 **라인 번호를 전부 제거하고 함수/메서드명으로 전환**했다.

---

## 1. `bind_tools` / `@tool` / `AgentExecutor` / `create_react_agent` 0건 주장

**검증 결과: 사실.**

프로젝트 전체(`node_modules` 제외) 검색에서 이 네 심볼의 히트는 **문서 본문 2곳뿐**이고,
파이썬 코드에는 0건이다. `initialize_agent`, `ToolNode`, `tool_calls`도 함께 검색했으나 0건.

| 검색어 | 코드 히트 | 문서 히트 |
|---|---|---|
| `bind_tools` | 0 | 2 (콜아웃 · 다이어그램) |
| `@tool` | 0 | 2 |
| `AgentExecutor` | 0 | 2 |
| `create_react_agent` | 0 | 2 |
| `initialize_agent` · `ToolNode` · `tool_calls` | 0 | 0 |

세 에이전트 모두 LCEL 체인(`prompt | llm | StrOutputParser()`)만 쓴다.
→ "결정론적 파이프라인" 주장의 근거는 유효하다.

---

## 2. 어긋난 참조 2건 (교정 완료)

| # | 문서 기존 표기 | 실제 | 교정 |
|---|---|---|---|
| 1 | `rag_agent.py:63-64` 의 `WHERE` 절에 결함명 하드코딩 | 63번째 줄은 `OPTIONAL MATCH (vsm:VirtualSensorModel)...` 이고 `WHERE` 절은 **64번째 줄 단독** | `GraphRAGAgent.get_context_from_graph()` 의 Cypher `WHERE` 절 |
| 2 | V1 훅 부착 위치 = `server.py:591` 직후 | 591번째 줄은 `recommendation = rag_res` 로 **if 분기 내부**. 그 직후는 `elif` 라 훅을 걸 수 없다 | `_run_anomaly_pipeline()` 에서 `explanation`·`recommendation` 이 **세 분기 합류 후 확정된 직후, `report_payload` 조립 이전** |

2번은 단순 오타가 아니라 **설계상 실수**였다. 591번째 줄 직후에 걸면
킬스위치 OFF·자동분석 OFF 분기를 타는 경우 검증이 실행되지 않는다.

---

## 3. 정확했던 참조 43건

### server.py
| 참조 | 실제 내용 | 판정 |
|---|---|---|
| `:71` | `InferenceEngine(lgbm_confidence_threshold=0.8)` | ○ |
| `:544-548` | `pred_idx` 결정 → `scaler.transform` → `explain` | ○ |
| `:548` | `explainer.explain(scaled, metrics, pred_idx)` | ○ |
| `:566` | `display_fault_name` 치환 (UNKNOWN FAULT → 감지된 결함) | ○ |
| `:573` | `openai_enabled() and LLM_ANALYSIS_ENABLED` | ○ |
| `:577-581` | `asyncio.gather(..., return_exceptions=True)` | ○ |
| `:582-591` / `:582-598` | 예외·비활성 분기 | ○ |
| `:601-611` | `report_payload` + broadcast | ○ |
| `:616-622` | Slack 발송 | ○ |
| `:632-636` | `_call_shap_agent()` | ○ |
| `:639-646` | `_call_rag_agent()` | ○ |
| `:661` | `@app.post("/api/rag_search")` | ○ |
| `:669` | `query = request.query` | ○ |
| `:675` / `:675-683` | 킬스위치 선차단 + `openai_disabled` 반환 | ○ |
| `:720` / `:720-730` | `_call_rag_v2()` | ○ |

### agents/
| 참조 | 실제 내용 | 판정 |
|---|---|---|
| `llm_guard.py:8-13` | "왜 생성자에서 막는가" 사고 경위 주석 | ○ |
| `llm_guard.py:36-44` | `openai_enabled()` + `ensure_openai_enabled()` | ○ |
| `llm_guard.py:41` | `ensure_openai_enabled()` 정의 | ○ |
| `shap_agent.py:11-12` | `OPEN_AI_API_KEY` → `OPENAI_API_KEY` shim | ○ |
| `shap_agent.py:22` | 생성자 가드 첫 줄 | ○ |
| `shap_agent.py:23-24` | `LLM_MODEL` 기본값 + `temperature=0` | ○ |
| `shap_agent.py:25-58` | 프롬프트 + `explain_fault()` | ○ |
| `shap_agent.py:39` | 프롬프트 5항 문구 검열 | ○ |
| `shap_agent.py:42` | LCEL 체인 | ○ |
| `rag_agent.py:19` | 생성자 가드 | ○ |
| `rag_agent.py:33-39, 102` | system 인라인 컨텍스트 + `json.dumps` | ○ |
| `rag_agent.py:48` | LCEL 체인 | ○ |
| `rag_agent.py:53-92` | `get_context_from_graph()` | ○ |
| `rag_agent.py:94-113` | `get_recommendation()` | ○ |
| `rag_agent_v2.py:39-60` | `compact_shap()` | ○ |
| `rag_agent_v2.py:63-77` | `parse_shap_to_lists()` | ○ |
| `rag_agent_v2.py:100` | 생성자 가드 | ○ |
| `rag_agent_v2.py:111-123` | 슬림 프롬프트 | ○ |
| `rag_agent_v2.py:118-122` | user 메시지 `{question}` | ○ |
| `rag_agent_v2.py:124` | LCEL 체인 | ○ |
| `rag_agent_v2.py:132-158` | `stage1_match_fault()` | ○ |
| `rag_agent_v2.py:166-193` | `stage2_fetch_chain()` | ○ |
| `rag_agent_v2.py:182-187` | `sops` collect 절 | ○ |
| `rag_agent_v2.py:195-203` | `fetch_sop_steps()` + "Expensive" 독스트링 | ○ |
| `rag_agent_v2.py:208-233` | `_format_chain()` | ○ |
| `rag_agent_v2.py:269-328` | `recommend()` | ○ |

### 기타 모듈
| 참조 | 실제 내용 | 판정 |
|---|---|---|
| `worker.py:104-119` | 3-소스 병합 → `_process_and_send` | ○ |
| `inference.py:84` | `predict()` 정의 | ○ |
| `inference.py:113-143` | 5단계 판단 로직 | ○ |
| `shap_analysis.py:19-70` | `SHAPExplainer.explain()` | ○ |
| `slack.py:11-22` | `_TEXT_LIMIT=2800` + `_truncate()` | ○ |
| `slack.py:25-56` | `_format_shap_lines()` | ○ |
| `store.py:146-147` | 적재 실패를 삼키는 except 블록 | ○ |
| `validation/rag_assessment.py:39` | 존재하지 않는 `agent.run()` 호출 | ○ |
| `neo4j_loader_v2.py:178-198` | `faults` 테이블 F01~F21 | ○ |

---

## 4. 수치 주장 검증

### "결함 21종 중 서로 다른 지문은 12종" — **사실**

`Neo4jLoaderV2.load_fault_layer()` 의 `faults` 테이블에서 `(sensors_low, sensors_high)`
튜플의 고유값을 세면 정확히 12개다.

| 지문 | 해당 결함 | 개수 |
|---|---|---|
| high=[TCP Top Power] | F01 TCP+50, F05 TCP+10, F10 TCP+30, F21 TCP+20 | 4 |
| low=[RF Bottom Power] | F02 RF-12, F18 RF-12(v2) | 2 |
| high=[RF Bottom Power] | F03 RF+10, F12 RF+8 | 2 |
| high=[Chamber Pressure, Vat Valve] | F04 Pr+3 | 1 |
| high=[BCl3 Flow] | F06 BCl3+5, F19 BCl3+10 | 2 |
| low=[Chamber Pressure] | F07 Pr-2 | 1 |
| low=[Cl2 Flow] | F08 Cl2-5, F17 Cl2-10 | 2 |
| low=[Helium Pressure] | F09 He Chuck | 1 |
| high=[Cl2 Flow] | F11 Cl2+5 | 1 |
| low=[BCl3 Flow] | F13 BCl3-5 | 1 |
| high=[Chamber Pressure] | F14 Pr+2, F20 Pr+1 | 2 |
| low=[TCP Top Power] | F15 TCP-20, F16 TCP-15 | 2 |
| **합계** | **12 지문 그룹** | **21** |

`hits/fp_size` 스코어가 동점(1.0)이 되는 것도 맞다. 지문 크기가 1인 결함은
매칭 시 `1/1 = 1.0`이 되어 4개가 완전 동점이다.
→ 정확 Top-1 상한 `12/21 ≈ 57%` 주장은 유효.

### README "노드 116개, SOP 5건" — **사실**

로더 기준 노드 수: 장비/공정 12 + 센서 22 + 가상센서 9 + 결함 25 + 원인 16 + SOP 32 = **116**.
(로더 자체 출력은 `~120` 으로 어림값이라 README 쪽이 더 정확하다.)

### v1 Cypher "OPTIONAL MATCH 6단" — **부정확 (교정)**

실제는 `MATCH` 1개 + `OPTIONAL MATCH` **5개**. → "MATCH 1 + OPTIONAL MATCH 5단"으로 수정.

---

## 5. 반영한 수정 목록

### README.md
- 사전 준비의 파이썬 절대경로 제거 (Windows 사용자명이 노출되고 있었다).
- 디렉터리명을 저장소명 `etch_proj_final` 로 통일(구조도와 일치).
- "알려진 제약"의 `.env` 가 `.gitignore` 에 없다 문장 삭제. 대신 실제 조치(`.gitignore` 생성).
- `.env` 블록 뒤에 이후 `python` 명령이 venv 파이썬을 가리킨다는 한 줄 추가.

### agent-architecture.html (구 onepager)
- 파일명·제목에서 `onepager` 제거 → **아키텍처 상세 문서**로 재명명.
- `@media print` 안에 `:root` 라이트 팔레트 재선언 + `print-color-adjust:exact`.
  다크모드 OS에서 PDF 출력해도 흰 종이에 어두운 박스가 박히지 않는다.
- 첫 콜아웃 순서 반전: "이건 agent가 아니다" → **"무인 24/7에서는 결정론적 실행 순서가 요건이다 → 그래서 agentic loop를 의도적으로 배제했다"**. 0건은 누락이 아니라 선택의 결과로 배치.
- 다이어그램 ✕ 문구도 "존재하지 않는다" → "설계상 배제했다"로 조정.
- 근거 참조 45곳 전부 라인 번호 제거 → 함수/메서드명 표기.
- 5장에 v1 Cypher가 현행 KG에 없는 관계(`FIXED_BY` 등)를 쓴다는 사실 보강.
- 5장 SHAP 호환성 항목에 실제 `direction` 값이 `"Positive Influence"`/`"Negative Influence"` 라는 점 명시.

### 신규
- `.gitignore` 생성 — `.env`, 키/인증서, `__pycache__`, `node_modules`, `logs/`, `reports/` 등.

---

## 6. 미조치

**이전 원격 저장소에 `.env` 가 커밋되어 있었다.**

`.gitignore` 를 추가해 앞으로는 커밋되지 않지만, 이전 저장소 히스토리에 남은 것은
그쪽에서 따로 정리해야 한다. 그리고 이미 노출된 자격증명은 히스토리를 지워도
안전해지지 않으므로 **OpenAI 키 · Neo4j 비밀번호 · Slack Webhook URL 재발급이 먼저다.**
