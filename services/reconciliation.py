"""DART ↔ SAP 대사(reconciliation) 엔진.

핵심 철학: 숫자 계산과 상태 판정은 100% deterministic Python 코드로 수행한다.
LLM 은 이 결과를 '해석'만 하며, 어떤 숫자도 계산하지 않는다.
"""

from __future__ import annotations

import io

import pandas as pd

from data.account_mapping import canonical_account_name

# 상태 상수
STATUS_OK = "정상"
STATUS_CHECK = "확인 필요"
STATUS_MISSING = "데이터 누락"
STATUS_NO_CONTROL = "통제 매핑 필요"

STATUS_ORDER = [STATUS_CHECK, STATUS_MISSING, STATUS_NO_CONTROL, STATUS_OK]


class FileFormatError(Exception):
    """업로드 파일 형식 오류를 사용자에게 설명하기 위한 예외."""


# ---------------------------------------------------------------------------
# 파일 로딩
# ---------------------------------------------------------------------------

def _read_tabular(file_obj, filename: str) -> pd.DataFrame:
    """CSV(utf-8/utf-8-sig/cp949) 또는 XLSX 를 DataFrame 으로 로딩."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        try:
            return pd.read_excel(file_obj)
        except Exception as e:
            raise FileFormatError(f"엑셀 파일을 읽을 수 없습니다: {e}") from e
    # CSV: 인코딩 순차 시도
    raw = file_obj.read() if hasattr(file_obj, "read") else file_obj
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise FileFormatError(f"CSV 파일을 읽을 수 없습니다: {e}") from e
    raise FileFormatError("CSV 인코딩을 인식할 수 없습니다 (utf-8 / cp949 지원).")


def load_sap_file(file_obj, filename: str) -> pd.DataFrame:
    """SAP 시산표 업로드 파일 검증 및 로딩.

    필수 컬럼: account_name, amount (account_code 는 선택)
    """
    df = _read_tabular(file_obj, filename)
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"account_name", "amount"}
    missing = required - set(df.columns)
    if missing:
        raise FileFormatError(
            f"SAP 파일에 필수 컬럼이 없습니다: {', '.join(sorted(missing))} "
            f"(필요 컬럼: account_code, account_name, amount)"
        )
    df["account_name"] = df["account_name"].astype(str).str.strip()
    df["amount"] = pd.to_numeric(
        df["amount"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    )
    if df["amount"].isna().all():
        raise FileFormatError("SAP 파일의 amount 컬럼에서 숫자를 읽을 수 없습니다.")
    df = df.dropna(subset=["amount"]).reset_index(drop=True)
    df["amount"] = df["amount"].astype("int64")
    return df


def load_rcm_file(file_obj, filename: str) -> pd.DataFrame:
    """RCM 업로드 파일 검증 및 로딩.

    필수 컬럼: control_id, account_name, control_name, tolerance
    선택 컬럼: required_evidence
    """
    df = _read_tabular(file_obj, filename)
    df.columns = [str(c).strip().lower() for c in df.columns]
    required = {"control_id", "account_name", "control_name", "tolerance"}
    missing = required - set(df.columns)
    if missing:
        raise FileFormatError(
            f"RCM 파일에 필수 컬럼이 없습니다: {', '.join(sorted(missing))} "
            f"(필요 컬럼: control_id, account_name, control_name, tolerance, required_evidence)"
        )
    if "required_evidence" not in df.columns:
        df["required_evidence"] = ""
    df["account_name"] = df["account_name"].astype(str).str.strip()
    df["tolerance"] = pd.to_numeric(
        df["tolerance"].astype(str).str.replace(",", "", regex=False), errors="coerce"
    ).fillna(0).astype("int64")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 대사 엔진 (deterministic)
# ---------------------------------------------------------------------------

def reconcile(
    dart_df: pd.DataFrame,
    sap_df: pd.DataFrame,
    rcm_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """DART / SAP / RCM 을 canonical 계정명 기준으로 결합하고 상태를 판정한다.

    판정 규칙 (우선순위 순):
      1) DART 또는 SAP 값 없음            → 데이터 누락
      2) RCM 통제 없음                     → 통제 매핑 필요
      3) abs(차이) <= tolerance            → 정상
      4) abs(차이) >  tolerance            → 확인 필요
    """
    dart_map: dict[str, int] = {}
    for _, r in dart_df.iterrows():
        key = canonical_account_name(r["account_name"])
        if key and key not in dart_map and pd.notna(r["amount"]):
            dart_map[key] = int(r["amount"])

    sap_map: dict[str, int] = {}
    sap_code_map: dict[str, str] = {}
    for _, r in sap_df.iterrows():
        key = canonical_account_name(r["account_name"])
        if key and key not in sap_map:
            sap_map[key] = int(r["amount"])
            if "account_code" in sap_df.columns:
                sap_code_map[key] = str(r["account_code"])

    rcm_map: dict[str, dict] = {}
    if rcm_df is not None and len(rcm_df) > 0:
        for _, r in rcm_df.iterrows():
            key = canonical_account_name(r["account_name"])
            if key and key not in rcm_map:
                rcm_map[key] = {
                    "control_id": str(r["control_id"]).strip(),
                    "control_name": str(r["control_name"]).strip(),
                    "tolerance": int(r["tolerance"]),
                    "required_evidence": str(r.get("required_evidence", "")).strip(),
                }

    all_accounts = list(dict.fromkeys(list(dart_map) + list(sap_map)))

    rows = []
    for acct in all_accounts:
        dart_amt = dart_map.get(acct)
        sap_amt = sap_map.get(acct)
        rcm = rcm_map.get(acct)

        diff = None
        diff_pct = None
        if dart_amt is not None and sap_amt is not None:
            diff = sap_amt - dart_amt
            diff_pct = round(abs(diff) / abs(dart_amt) * 100, 4) if dart_amt != 0 else None

        # --- 상태 판정 (deterministic) ---
        if dart_amt is None or sap_amt is None:
            status = STATUS_MISSING
        elif rcm is None:
            status = STATUS_NO_CONTROL
        elif abs(diff) <= rcm["tolerance"]:
            status = STATUS_OK
        else:
            status = STATUS_CHECK

        rows.append(
            {
                "account_name": acct,
                "sap_account_code": sap_code_map.get(acct, ""),
                "dart_amount": dart_amt,
                "sap_amount": sap_amt,
                "diff": diff,
                "diff_pct": diff_pct,
                "control_id": rcm["control_id"] if rcm else "",
                "control_name": rcm["control_name"] if rcm else "",
                "tolerance": rcm["tolerance"] if rcm else None,
                "required_evidence": rcm["required_evidence"] if rcm else "",
                "status": status,
            }
        )

    result = pd.DataFrame(rows)
    if len(result) > 0:
        result["_order"] = result["status"].map({s: i for i, s in enumerate(STATUS_ORDER)})
        result = result.sort_values(["_order", "account_name"]).drop(columns=["_order"])
        result = result.reset_index(drop=True)
    return result


def summarize(result: pd.DataFrame) -> dict[str, int]:
    """KPI 카드용 요약."""
    counts = result["status"].value_counts().to_dict() if len(result) else {}
    return {
        "total": int(len(result)),
        STATUS_OK: int(counts.get(STATUS_OK, 0)),
        STATUS_CHECK: int(counts.get(STATUS_CHECK, 0)),
        STATUS_MISSING: int(counts.get(STATUS_MISSING, 0)),
        STATUS_NO_CONTROL: int(counts.get(STATUS_NO_CONTROL, 0)),
    }


def exceptions_only(result: pd.DataFrame) -> pd.DataFrame:
    """AI 검토 대상: 정상을 제외한 예외 항목만."""
    return result[result["status"] != STATUS_OK].reset_index(drop=True)


# ---------------------------------------------------------------------------
# 실제 DART 데이터 기반 데모용 SAP 샘플 생성
# ---------------------------------------------------------------------------

def generate_demo_sap_csv(dart_df: pd.DataFrame) -> bytes:
    """실제 조회된 DART 숫자를 기준으로, 데모 시나리오(일치/오차이내/오차초과/누락/추가)를
    포함한 SAP 시산표 CSV 를 생성한다. 실제 API 데이터로 시연할 때 사용."""
    rows = []
    code = 100000
    for i, (_, r) in enumerate(dart_df.iterrows()):
        acct = canonical_account_name(r["account_name"])
        amt = r["amount"]
        if pd.isna(amt):
            continue
        amt = int(amt)
        if acct == "매출액":
            amt -= 50_000_000       # 허용오차 초과 → 확인 필요
        elif acct == "당기순이익":
            amt -= 5_000_000        # 허용오차 이내 → 정상
        elif acct == "유동자산":
            continue                 # DART 에만 존재 → 데이터 누락
        rows.append({"account_code": code + i * 10000, "account_name": acct, "amount": amt})
    # SAP 에만 존재하는 계정 (DART 없음 → 데이터 누락)
    rows.append({"account_code": 520000, "account_name": "판매비와관리비", "amount": 890_000_000})
    # RCM 통제가 없는 계정 (양쪽 존재 가정 시나리오용 - DART 주요계정에 없으므로 데이터 누락으로 표시됨)
    df = pd.DataFrame(rows)
    return df.to_csv(index=False).encode("utf-8-sig")
