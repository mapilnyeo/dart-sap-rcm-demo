"""검토 결과 내보내기: Google Sheets 또는 XLSX/CSV.

- GOOGLE_SERVICE_ACCOUNT_JSON + GOOGLE_SHEET_ID 가 설정되어 있으면 실제 시트에 기록
- 없으면 XLSX/CSV 다운로드로 대체 (앱은 절대 죽지 않는다)
"""

from __future__ import annotations

import io
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

EXPORT_COLUMNS = [
    "검토일",
    "회사",
    "사업연도",
    "계정명",
    "DART 금액",
    "SAP 금액",
    "차이",
    "차이율",
    "RCM Control ID",
    "통제명",
    "상태",
    "AI 검토의견",
    "담당자 확인질문",
    "최종 검토상태",
]


def build_export_df(
    result_df: pd.DataFrame,
    company: str,
    year: str,
    ai_reviews: dict[str, dict] | None = None,
    ai_questions: dict[str, str] | None = None,
) -> pd.DataFrame:
    """대사 결과 + AI 의견을 내보내기 스키마로 변환."""
    ai_reviews = ai_reviews or {}
    ai_questions = ai_questions or {}
    today = date.today().isoformat()

    rows = []
    for _, r in result_df.iterrows():
        acct = r["account_name"]
        review = ai_reviews.get(acct, {})
        rows.append(
            {
                "검토일": today,
                "회사": company,
                "사업연도": year,
                "계정명": acct,
                "DART 금액": r["dart_amount"] if pd.notna(r["dart_amount"]) else "",
                "SAP 금액": r["sap_amount"] if pd.notna(r["sap_amount"]) else "",
                "차이": r["diff"] if pd.notna(r["diff"]) else "",
                "차이율": f"{r['diff_pct']}%" if pd.notna(r["diff_pct"]) else "",
                "RCM Control ID": r["control_id"],
                "통제명": r["control_name"],
                "상태": r["status"],
                "AI 검토의견": review.get("text", ""),
                "담당자 확인질문": ai_questions.get(acct, ""),
                "최종 검토상태": "검토 대기",
            }
        )
    return pd.DataFrame(rows, columns=EXPORT_COLUMNS)


# ---------------------------------------------------------------------------
# 파일 다운로드 (항상 가능)
# ---------------------------------------------------------------------------

def to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="내부회계검토결과")
        ws = writer.sheets["내부회계검토결과"]
        widths = [12, 14, 10, 14, 18, 18, 15, 9, 14, 26, 12, 60, 50, 12]
        for i, w in enumerate(widths[: len(df.columns)], start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    return buf.getvalue()


def to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Google Sheets (선택)
# ---------------------------------------------------------------------------

def google_sheets_configured() -> bool:
    return bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()) and bool(
        os.getenv("GOOGLE_SHEET_ID", "").strip()
    )


def _load_credentials():
    from google.oauth2.service_account import Credentials

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if raw.startswith("{"):
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=scopes)
    path = Path(raw)
    if not path.exists():
        raise FileNotFoundError(f"서비스 계정 JSON 파일을 찾을 수 없습니다: {raw}")
    return Credentials.from_service_account_file(str(path), scopes=scopes)


def export_to_google_sheets(df: pd.DataFrame) -> str:
    """결과를 새 워크시트 탭에 기록하고 시트 URL 반환.

    실패 시 예외를 던진다 (호출부에서 XLSX fallback 안내).
    """
    import gspread

    creds = _load_credentials()
    gc = gspread.authorize(creds)
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
    sh = gc.open_by_key(sheet_id)

    title_base = f"검토결과_{date.today().isoformat()}"
    title = title_base
    existing = {ws.title for ws in sh.worksheets()}
    n = 2
    while title in existing:
        title = f"{title_base}_{n}"
        n += 1

    ws = sh.add_worksheet(title=title, rows=len(df) + 10, cols=len(df.columns) + 2)
    values = [list(df.columns)] + df.astype(str).replace("nan", "").values.tolist()
    ws.update(values, "A1")
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}#gid={ws.id}"
