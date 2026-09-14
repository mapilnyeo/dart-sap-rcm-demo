"""AI 검토의견 생성 모듈.

설계 원칙:
  - AI 는 숫자를 계산하지 않는다. Python 이 계산한 결과만 전달받아 '해석'한다.
  - provider 는 환경변수 AI_PROVIDER 로 교체 가능: mock | claude | openai | gemini
  - API Key 가 없거나 호출이 실패하면 deterministic mock 결과로 fallback 한다.

외부 SDK 없이 requests 로 각 provider 의 REST API 를 직접 호출한다.
"""

from __future__ import annotations

import os

import requests

TIMEOUT = 60

SYSTEM_PROMPT = """당신은 내부회계 검토 보조 AI입니다.

제공되지 않은 사실을 추측하지 마세요.

근거가 없는 경우 반드시 "확인 필요"라고 표시하세요.

숫자를 새로 계산하지 마세요.
제공된 계산 결과만 사용하세요.

회계 또는 법률적 최종 판단을 내리지 마세요.

AI의 결과는 담당자의 검토가 필요한 초안입니다.

출력은 반드시 아래 형식을 따르세요.

가능한 원인
- (항목별 나열)

추가 확인 자료
- (항목별 나열)

담당자 확인 질문
"(한 문장의 구체적 질문)"

평가의견 초안
"(2~3문장의 초안. 단정하지 말고 '추가 확인이 필요합니다' 톤 유지)"
"""


def _fmt_amount(v) -> str:
    if v is None:
        return "없음"
    return f"{int(v):,}원"


def build_context_text(ctx: dict) -> str:
    """대사 결과 1건을 AI 에게 전달할 텍스트로 변환 (숫자는 이미 계산 완료)."""
    lines = [
        f"회사: {ctx.get('company', '미지정')}",
        f"사업연도: {ctx.get('year', '미지정')}",
        f"계정명: {ctx['account_name']}",
        f"판정 상태: {ctx['status']}",
        f"DART 공시금액: {_fmt_amount(ctx.get('dart_amount'))}",
        f"SAP 시산표금액: {_fmt_amount(ctx.get('sap_amount'))}",
        f"차이 (SAP-DART): {_fmt_amount(ctx.get('diff')) if ctx.get('diff') is not None else '계산 불가'}",
        f"차이율: {ctx['diff_pct']}%" if ctx.get("diff_pct") is not None else "차이율: 계산 불가",
        f"RCM Control: {ctx.get('control_id') or '매핑된 통제 없음'}"
        + (f" ({ctx.get('control_name')})" if ctx.get("control_name") else ""),
        f"허용오차(tolerance): {_fmt_amount(ctx.get('tolerance')) if ctx.get('tolerance') is not None else '미정의'}",
        f"통제상 요구 증빙: {ctx.get('required_evidence') or '미정의'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _call_claude(user_text: str) -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 미설정")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.getenv("CLAUDE_MODEL", "claude-sonnet-5"),
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_text}],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return "".join(b.get("text", "") for b in data.get("content", []))


def _call_openai(user_text: str) -> str:
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY 미설정")
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "max_tokens": 1024,
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(user_text: str) -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY 미설정")
    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": key},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


# ---------------------------------------------------------------------------
# Deterministic mock (API Key 없이 데모 가능)
# ---------------------------------------------------------------------------

_MOCK_CAUSES = {
    "확인 필요": [
        "결산조정분 미반영 가능성",
        "DART 공시 계정과 SAP 계정 범위(집계 단위) 차이",
        "공시 작성 시 계정 재분류/매핑 차이",
    ],
    "데이터 누락": [
        "한쪽 시스템(DART 또는 SAP)에 해당 계정이 집계되지 않음",
        "계정명 불일치로 자동 매핑 실패 가능성 (alias 미등록)",
        "공시 주요계정 범위에 포함되지 않는 세부 계정일 가능성",
    ],
    "통제 매핑 필요": [
        "RCM 에 해당 계정에 대한 통제활동이 정의되어 있지 않음",
        "신규 계정 또는 통제 문서화 누락 가능성",
    ],
}

_MOCK_EVIDENCE = {
    "확인 필요": ["결산조정 내역", "공시 작성용 계정 매핑표"],
    "데이터 누락": ["SAP 계정과목표(Chart of Accounts)", "공시 작성 기초자료", "계정 매핑 기준서"],
    "통제 매핑 필요": ["RCM 최신본", "해당 계정 관련 프로세스 문서"],
}


def _mock_review(ctx: dict) -> str:
    status = ctx["status"]
    acct = ctx["account_name"]
    causes = _MOCK_CAUSES.get(status, ["원인 정보 부족 → 확인 필요"])
    evidence = list(_MOCK_EVIDENCE.get(status, []))
    if ctx.get("required_evidence"):
        evidence.insert(0, ctx["required_evidence"])

    if status == "확인 필요":
        diff = ctx.get("diff")
        diff_txt = _fmt_amount(abs(diff)) if diff is not None else "확인 필요"
        question = (
            f"공시 작성 시 SAP {acct} 외 별도 결산조정 {diff_txt}이(가) "
            f"반영되었는지 확인해 주세요."
        )
        opinion = (
            f"DART 공시금액과 SAP 시산표 간 {diff_txt}의 차이가 확인되었습니다. "
            f"허용오차({_fmt_amount(ctx.get('tolerance'))})를 초과하므로 "
            f"결산조정 및 공시 계정 매핑 여부에 대한 추가 확인이 필요합니다."
        )
    elif status == "데이터 누락":
        side = "SAP 시산표" if ctx.get("sap_amount") is None else "DART 공시"
        question = f"{acct} 계정이 {side}에서 확인되지 않습니다. 계정명 매핑 또는 집계 범위를 확인해 주세요."
        opinion = (
            f"{acct} 계정의 {side} 금액이 확인되지 않아 대사를 완료할 수 없습니다. "
            f"계정 매핑 기준 및 데이터 집계 범위에 대한 추가 확인이 필요합니다."
        )
    else:  # 통제 매핑 필요
        question = f"{acct} 계정에 대한 통제활동이 RCM 에 정의되어 있는지 확인해 주세요."
        opinion = (
            f"{acct} 계정에 매핑된 RCM 통제가 확인되지 않습니다. "
            f"통제 신설 또는 기존 통제와의 매핑에 대한 추가 확인이 필요합니다."
        )

    lines = ["가능한 원인"]
    lines += [f"- {c}" for c in causes]
    lines += ["", "추가 확인 자료"]
    lines += [f"- {e}" for e in evidence]
    lines += ["", "담당자 확인 질문", f'"{question}"', "", "평가의견 초안", f'"{opinion}"']
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_PROVIDERS = {"claude": _call_claude, "openai": _call_openai, "gemini": _call_gemini}


def active_provider() -> str:
    """현재 실제로 사용될 provider 이름 (키 유무 반영)."""
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    key_env = {"claude": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}
    if provider in _PROVIDERS and os.getenv(key_env[provider], "").strip():
        return provider
    return "mock"


def generate_review_comment(ctx: dict) -> dict:
    """예외 항목 1건에 대한 AI 검토의견 생성.

    반환: {"provider": str, "text": str, "fallback_reason": str|None}
    """
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    user_text = (
        "아래는 시스템(Python)이 이미 계산 완료한 내부회계 대사 결과입니다. "
        "이 계산 결과를 근거로만 해석하세요.\n\n" + build_context_text(ctx)
    )

    if provider in _PROVIDERS:
        try:
            text = _PROVIDERS[provider](user_text)
            if text and text.strip():
                return {"provider": provider, "text": text.strip(), "fallback_reason": None}
            raise RuntimeError("빈 응답")
        except Exception as e:
            return {
                "provider": "mock",
                "text": _mock_review(ctx),
                "fallback_reason": f"{provider} 호출 실패 → mock 사용 ({e})",
            }

    return {"provider": "mock", "text": _mock_review(ctx), "fallback_reason": None}


def extract_question(review_text: str) -> str:
    """검토의견 텍스트에서 '담당자 확인 질문' 섹션 추출 (내보내기용)."""
    lines = review_text.splitlines()
    for i, line in enumerate(lines):
        if "담당자 확인 질문" in line:
            for j in range(i + 1, min(i + 4, len(lines))):
                candidate = lines[j].strip().strip('"')
                if candidate:
                    return candidate
    return ""
