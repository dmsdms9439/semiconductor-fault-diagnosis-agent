"""
OpenAI 호출 총괄 킬 스위치.

.env 의 OPENAI_ENABLED=false 이면 LLM 에이전트 생성 자체를 막아, 어느 경로로
들어오든(실시간 파이프라인 / REST /api/rag_search / 검증 스크립트) OpenAI
과금이 발생하지 않게 한다.

왜 생성자에서 막는가:
  호출 지점마다 if 조건을 다는 방식은 빠뜨리기 쉽다. 실제로 LLM_ANALYSIS_ENABLED
  게이트가 실시간 파이프라인에만 걸려 있어서, /api/rag_search 와 당시의 Streamlit
  데모(app.py, 현재는 제거됨) 2곳이 무방비로 과금되고 있었다. 그래서 개별 호출부
  가드(사용자에게 깔끔한 메시지를 보여주기 위함)와 별개로, 에이전트 __init__
  에서 한 번 더 차단한다.

값은 import 시점이 아니라 호출 시점에 읽는다(os.getenv). 단, load_dotenv 는
프로세스 시작 시 1회만 반영되므로 .env 를 고쳤으면 서버 재시작이 필요하다.
"""

import os

from dotenv import load_dotenv

load_dotenv()

DISABLED_MESSAGE = (
    "OpenAI 호출이 비활성화되어 있습니다 (비용 절감). "
    "SHAP 기여도 분석은 LLM 없이 정상 제공됩니다. "
    "다시 켜려면 .env 의 OPENAI_ENABLED=true 로 바꾼 뒤 서버를 재시작하세요."
)


class OpenAIDisabledError(RuntimeError):
    """OPENAI_ENABLED=false 상태에서 LLM 에이전트를 생성하려 한 경우."""


def openai_enabled() -> bool:
    """OpenAI 호출 허용 여부. 미설정 시 기본 true(기존 동작 유지)."""
    return os.getenv("OPENAI_ENABLED", "true").lower() == "true"


def ensure_openai_enabled() -> None:
    """차단 상태면 OpenAIDisabledError 를 던진다. 에이전트 __init__ 에서 호출."""
    if not openai_enabled():
        raise OpenAIDisabledError(DISABLED_MESSAGE)
