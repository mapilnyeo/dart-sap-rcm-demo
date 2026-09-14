"""OpenDART 전자공시 API 연동.

공식 문서: https://opendart.fss.or.kr/guide/main.do
사용 endpoint:
  - 고유번호(corpCode) 파일: https://opendart.fss.or.kr/api/corpCode.xml
  - 단일회사 주요계정:       https://opendart.fss.or.kr/api/fnlttSinglAcnt.json

주요계정 API 는 재무상태표/손익계산서의 핵심 계정
(유동자산, 자산총계, 부채총계, 자본총계, 매출액, 영업이익, 당기순이익 등)을 반환한다.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://opendart.fss.or.kr/api"
TIMEOUT = 20

# reprt_code (공시 보고서 코드) - OpenDART 공식 코드값
REPORT_CODES = {
    "사업보고서": "11011",
    "반기보고서": "11012",
    "1분기보고서": "11013",
    "3분기보고서": "11014",
}

# fs_div: CFS 연결재무제표 / OFS 재무제표(별도)
FS_DIVS = {
    "연결재무제표(CFS)": "CFS",
    "별도재무제표(OFS)": "OFS",
}

_CORP_CACHE_FILE = Path(__file__).resolve().parent.parent / ".cache_corp_codes.parquet"


class DartError(Exception):
    """OpenDART 호출 실패를 사용자에게 설명하기 위한 예외."""


@dataclass
class DartAccount:
    account_name: str
    amount: int | None
    sj_div: str  # BS / IS
    raw_name: str


def get_api_key() -> str | None:
    key = os.getenv("DART_API_KEY", "").strip()
    return key or None


def _request_json(endpoint: str, params: dict) -> dict:
    url = f"{BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise DartError(f"OpenDART 서버에 연결할 수 없습니다: {e}") from e
    if resp.status_code != 200:
        raise DartError(f"OpenDART HTTP 오류 (status {resp.status_code})")
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise DartError("OpenDART 응답을 해석할 수 없습니다 (JSON 아님).") from e

    status = data.get("status")
    if status and status != "000":
        messages = {
            "010": "등록되지 않은 인증키입니다. .env 의 DART_API_KEY 를 확인하세요.",
            "011": "사용할 수 없는 인증키입니다 (기간 만료 등).",
            "012": "접근할 수 없는 IP 입니다.",
            "013": "조회된 데이터가 없습니다. 사업연도/보고서 종류/재무제표 구분을 확인하세요.",
            "014": "파일이 존재하지 않습니다.",
            "020": "요청 제한(일 20,000건)을 초과했습니다.",
            "100": "필드 값이 부적절합니다.",
            "800": "시스템 점검 중입니다.",
            "900": "정의되지 않은 오류입니다.",
        }
        msg = messages.get(status, data.get("message", "알 수 없는 오류"))
        raise DartError(f"OpenDART 오류 [{status}] {msg}")
    return data


# ---------------------------------------------------------------------------
# 회사 검색 (corpCode)
# ---------------------------------------------------------------------------

def load_corp_codes(api_key: str, force_refresh: bool = False) -> pd.DataFrame:
    """OpenDART 고유번호 전체 목록 다운로드 (zip → xml). 로컬 캐시 사용."""
    if _CORP_CACHE_FILE.exists() and not force_refresh:
        try:
            return pd.read_parquet(_CORP_CACHE_FILE)
        except Exception:
            pass  # 캐시 손상 시 재다운로드

    url = f"{BASE_URL}/corpCode.xml"
    try:
        resp = requests.get(url, params={"crtfc_key": api_key}, timeout=60)
    except requests.exceptions.RequestException as e:
        raise DartError(f"corpCode 다운로드 실패: {e}") from e

    # 오류 시 zip 이 아니라 XML/JSON 오류 본문이 온다
    if resp.content[:2] != b"PK":
        text = resp.text[:500]
        if "010" in text:
            raise DartError("등록되지 않은 인증키입니다. .env 의 DART_API_KEY 를 확인하세요.")
        raise DartError(f"corpCode 다운로드 실패: {text}")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        with zf.open("CORPCODE.xml") as f:
            tree = ET.parse(f)

    rows = []
    for el in tree.getroot().iter("list"):
        rows.append(
            {
                "corp_code": (el.findtext("corp_code") or "").strip(),
                "corp_name": (el.findtext("corp_name") or "").strip(),
                "stock_code": (el.findtext("stock_code") or "").strip(),
            }
        )
    df = pd.DataFrame(rows)
    try:
        df.to_parquet(_CORP_CACHE_FILE, index=False)
    except Exception:
        pass  # 캐시 실패는 무시
    return df


def search_company(api_key: str, name: str) -> pd.DataFrame:
    """회사명 부분일치 검색. 상장사(stock_code 있음) 우선 정렬."""
    df = load_corp_codes(api_key)
    q = name.strip()
    if not q:
        return df.head(0)
    hit = df[df["corp_name"].str.contains(q, case=False, na=False, regex=False)].copy()
    hit["is_listed"] = hit["stock_code"] != ""
    hit = hit.sort_values(["is_listed", "corp_name"], ascending=[False, True])
    return hit.drop(columns=["is_listed"]).head(30).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 재무정보 조회
# ---------------------------------------------------------------------------

def _parse_amount(value: str) -> int | None:
    if value is None:
        return None
    s = str(value).replace(",", "").strip()
    if s in ("", "-"):
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def fetch_financials(
    api_key: str,
    corp_code: str,
    bsns_year: str,
    reprt_code: str,
    fs_div: str = "CFS",
) -> pd.DataFrame:
    """단일회사 주요계정 조회 → DataFrame(account_name, amount, sj_div).

    fnlttSinglAcnt 는 CFS/OFS 행을 함께 반환하므로 fs_div 로 필터한다.
    CFS 데이터가 없으면(비연결 대상 회사) OFS 로 자동 fallback 한다.
    """
    data = _request_json(
        "fnlttSinglAcnt.json",
        {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
        },
    )
    items = data.get("list", [])
    if not items:
        raise DartError("조회된 재무정보가 없습니다. 사업연도/보고서 종류를 확인하세요.")

    def rows_for(div: str) -> list[dict]:
        out = []
        for it in items:
            if it.get("fs_div") != div:
                continue
            out.append(
                {
                    "account_name": (it.get("account_nm") or "").strip(),
                    "amount": _parse_amount(it.get("thstrm_amount")),
                    "sj_div": it.get("sj_div", ""),
                    "fs_div": div,
                    "fs_nm": it.get("fs_nm", ""),
                }
            )
        return out

    rows = rows_for(fs_div)
    used_div = fs_div
    if not rows:
        fallback = "OFS" if fs_div == "CFS" else "CFS"
        rows = rows_for(fallback)
        used_div = fallback
    if not rows:
        raise DartError("선택한 재무제표 구분(CFS/OFS)에 해당하는 데이터가 없습니다.")

    df = pd.DataFrame(rows)
    # 동일 계정명이 BS/IS 에 중복될 일은 주요계정에서는 없지만 안전하게 첫 값 사용
    df = df.drop_duplicates(subset=["account_name"], keep="first").reset_index(drop=True)
    df.attrs["fs_div_used"] = used_div
    return df


# ---------------------------------------------------------------------------
# 오프라인 데모용 샘플 (API Key 없이도 전체 흐름 시연 가능)
# ---------------------------------------------------------------------------

SAMPLE_DART_DATA = [
    # (계정명, 금액, 재무제표구분)
    ("유동자산", 21_000_000_000, "BS"),
    ("자산총계", 45_000_000_000, "BS"),
    ("부채총계", 18_000_000_000, "BS"),
    ("자본총계", 27_000_000_000, "BS"),
    ("매출액", 12_000_000_000, "IS"),
    ("매출원가", 5_200_000_000, "IS"),   # RCM 통제 미정의 시나리오용
    ("영업이익", 1_450_000_000, "IS"),
    ("당기순이익", 1_055_000_000, "IS"),
]


def sample_financials() -> pd.DataFrame:
    """API Key 가 없거나 호출 실패 시 데모용 샘플 DART 데이터."""
    df = pd.DataFrame(
        [
            {"account_name": n, "amount": a, "sj_div": d, "fs_div": "CFS", "fs_nm": "연결재무제표(샘플)"}
            for n, a, d in SAMPLE_DART_DATA
        ]
    )
    df.attrs["fs_div_used"] = "CFS"
    return df
