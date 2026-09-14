"""계정명 정규화 및 alias 매핑.

DART 공시 계정명과 SAP 시산표 계정명이 완전히 같지 않은 경우를 대비해
canonical 계정명 ← alias 목록을 정의한다.
숫자 비교/판정 로직은 services/reconciliation.py 에서 수행한다 (LLM 미사용).
"""

# canonical name -> 허용되는 alias 목록 (canonical 자신도 포함)
ACCOUNT_ALIASES: dict[str, list[str]] = {
    "매출액": ["매출액", "영업수익", "수익(매출액)", "매출"],
    "매출원가": ["매출원가"],
    "영업이익": ["영업이익", "영업이익(손실)"],
    "당기순이익": ["당기순이익", "당기순이익(손실)", "연결당기순이익", "당기순손익"],
    "법인세차감전순이익": ["법인세차감전순이익", "법인세차감전 순이익", "법인세비용차감전순이익"],
    "판매비와관리비": ["판매비와관리비", "판매비와 관리비", "판관비"],
    "자산총계": ["자산총계", "자산 총계"],
    "부채총계": ["부채총계", "부채 총계"],
    "자본총계": ["자본총계", "자본 총계"],
    "자본금": ["자본금"],
    "이익잉여금": ["이익잉여금", "이익잉여금(결손금)"],
    "유동자산": ["유동자산"],
    "비유동자산": ["비유동자산"],
    "유동부채": ["유동부채"],
    "비유동부채": ["비유동부채"],
}


def _normalize(name: str) -> str:
    """공백 제거 등 단순 정규화."""
    return str(name).strip().replace(" ", "")


# alias(정규화형) -> canonical 역방향 인덱스
_ALIAS_INDEX: dict[str, str] = {}
for _canonical, _aliases in ACCOUNT_ALIASES.items():
    for _a in _aliases:
        _ALIAS_INDEX[_normalize(_a)] = _canonical


def canonical_account_name(name: str) -> str:
    """계정명을 canonical 명칭으로 변환. 매핑에 없으면 정규화된 원래 이름 반환."""
    if name is None:
        return ""
    key = _normalize(name)
    return _ALIAS_INDEX.get(key, str(name).strip())
