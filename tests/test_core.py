"""핵심 로직 테스트 (외부 API 호출 없이 실행 가능).

실행:  python tests/test_core.py
"""

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from data.account_mapping import canonical_account_name  # noqa: E402
from services import ai_review as ai  # noqa: E402
from services import dart as dart_svc  # noqa: E402
from services import google_sheets as gs  # noqa: E402
from services import reconciliation as rc  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


print("=== 1. 계정명 매핑 ===")
check("계정명 정확 일치", canonical_account_name("매출액") == "매출액")
check("alias 일치 (영업수익→매출액)", canonical_account_name("영업수익") == "매출액")
check("alias 일치 (수익(매출액)→매출액)", canonical_account_name("수익(매출액)") == "매출액")
check("alias 일치 (당기순이익(손실))", canonical_account_name("당기순이익(손실)") == "당기순이익")
check("공백 정규화 (자산 총계)", canonical_account_name("자산 총계") == "자산총계")
check("미등록 계정은 원본 유지", canonical_account_name("무형자산") == "무형자산")

print("=== 2. 파일 로딩 ===")
with open(ROOT / "samples" / "sap_trial_balance.csv", "rb") as f:
    sap_df = rc.load_sap_file(f, "sap_trial_balance.csv")
check("샘플 SAP 로딩 (8행)", len(sap_df) == 8, f"got {len(sap_df)}")

with open(ROOT / "samples" / "rcm_controls.csv", "rb") as f:
    rcm_df = rc.load_rcm_file(f, "rcm_controls.csv")
check("샘플 RCM 로딩 (7행)", len(rcm_df) == 7, f"got {len(rcm_df)}")

# 잘못된 형식 파일
bad = io.BytesIO("foo,bar\n1,2\n".encode("utf-8"))
try:
    rc.load_sap_file(bad, "bad.csv")
    check("SAP 잘못된 형식 → 오류 발생", False)
except rc.FileFormatError as e:
    check("SAP 잘못된 형식 → 오류 발생", "필수 컬럼" in str(e))

# cp949 인코딩 CSV
cp949 = io.BytesIO("account_code,account_name,amount\n410000,매출액,1000\n".encode("cp949"))
df_cp = rc.load_sap_file(cp949, "cp949.csv")
check("cp949 인코딩 CSV 로딩", df_cp.iloc[0]["account_name"] == "매출액")

print("=== 3. 대사 엔진 (deterministic) ===")
dart_df = dart_svc.sample_financials()
result = rc.reconcile(dart_df, sap_df, rcm_df)
by_acct = {r["account_name"]: r for _, r in result.iterrows()}

check("매출액: 차이 -50,000,000", by_acct["매출액"]["diff"] == -50_000_000)
check("매출액: 허용오차 초과 → 확인 필요", by_acct["매출액"]["status"] == rc.STATUS_CHECK)
check("영업이익: 완전 일치 → 정상", by_acct["영업이익"]["status"] == rc.STATUS_OK and by_acct["영업이익"]["diff"] == 0)
check("당기순이익: 오차 이내(-5,000,000) → 정상",
      by_acct["당기순이익"]["status"] == rc.STATUS_OK and by_acct["당기순이익"]["diff"] == -5_000_000)
check("자산총계: 일치 → 정상", by_acct["자산총계"]["status"] == rc.STATUS_OK)
check("유동자산: DART 에만 존재 → 데이터 누락",
      by_acct["유동자산"]["status"] == rc.STATUS_MISSING and pd.isna(by_acct["유동자산"]["sap_amount"]))
check("판매비와관리비: SAP 에만 존재 → 데이터 누락",
      by_acct["판매비와관리비"]["status"] == rc.STATUS_MISSING)
check("매출원가: RCM 없음 → 통제 매핑 필요", by_acct["매출원가"]["status"] == rc.STATUS_NO_CONTROL)
check("차이율 계산 (매출액 0.4167%)", abs(by_acct["매출액"]["diff_pct"] - 0.4167) < 0.001,
      f"got {by_acct['매출액']['diff_pct']}")

# RCM 없이 대사
result_no_rcm = rc.reconcile(dart_df, sap_df, None)
check("RCM 미업로드: 값 있는 계정은 통제 매핑 필요",
      all(r["status"] in (rc.STATUS_NO_CONTROL, rc.STATUS_MISSING) for _, r in result_no_rcm.iterrows()))

kpi = rc.summarize(result)
check("KPI 합계 = 전체", kpi["total"] == sum(kpi[s] for s in
      [rc.STATUS_OK, rc.STATUS_CHECK, rc.STATUS_MISSING, rc.STATUS_NO_CONTROL]))
exc = rc.exceptions_only(result)
check("예외만 추출 (정상 제외)", (exc["status"] != rc.STATUS_OK).all() and len(exc) == kpi["total"] - kpi[rc.STATUS_OK])

print("=== 4. AI 검토 (mock fallback) ===")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["AI_PROVIDER"] = "mock"
ctx = {
    "company": "JYP Ent.", "year": "2025", "account_name": "매출액", "status": "확인 필요",
    "dart_amount": 12_000_000_000, "sap_amount": 11_950_000_000, "diff": -50_000_000,
    "diff_pct": 0.4167, "control_id": "REV-01", "control_name": "매출 공시금액과 시산표 대사",
    "tolerance": 10_000_000, "required_evidence": "월별 매출 집계표",
}
review = ai.generate_review_comment(ctx)
check("mock provider 사용", review["provider"] == "mock")
check("검토의견 4개 섹션 포함", all(s in review["text"] for s in
      ["가능한 원인", "추가 확인 자료", "담당자 확인 질문", "평가의견 초안"]))
check("담당자 질문 추출", len(ai.extract_question(review["text"])) > 0)

# provider 를 claude 로 지정했지만 키 없음 → mock fallback
os.environ["AI_PROVIDER"] = "claude"
review2 = ai.generate_review_comment(ctx)
check("AI Key 없음 → mock fallback", review2["provider"] == "mock")
check("active_provider 도 mock 반환", ai.active_provider() == "mock")
os.environ["AI_PROVIDER"] = "mock"

# 데이터 누락 / 통제 매핑 필요 케이스
ctx_missing = dict(ctx, status="데이터 누락", sap_amount=None, diff=None, diff_pct=None)
check("데이터 누락 케이스 생성", "확인되지 않아" in ai.generate_review_comment(ctx_missing)["text"])
ctx_noctl = dict(ctx, status="통제 매핑 필요", control_id="", tolerance=None)
check("통제 매핑 필요 케이스 생성", "RCM" in ai.generate_review_comment(ctx_noctl)["text"])

print("=== 5. 내보내기 ===")
reviews = {"매출액": review}
questions = {"매출액": ai.extract_question(review["text"])}
export_df = gs.build_export_df(result, "JYP Ent.", "2025", reviews, questions)
check("내보내기 컬럼 14개", list(export_df.columns) == gs.EXPORT_COLUMNS)
check("행 수 일치", len(export_df) == len(result))
xlsx = gs.to_xlsx_bytes(export_df)
check("XLSX 생성 (xlsx magic)", xlsx[:2] == b"PK" and len(xlsx) > 1000)
csv = gs.to_csv_bytes(export_df)
check("CSV 생성 (utf-8-sig BOM)", csv[:3] == b"\xef\xbb\xbf")
check("Google 인증정보 없음 → 미설정 판정", gs.google_sheets_configured() is False
      if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") else True)

print("=== 6. DART 오류 처리 ===")
check("API Key 없음 판정", dart_svc.get_api_key() is None if not os.getenv("DART_API_KEY") else True)
try:
    dart_svc._request_json("fnlttSinglAcnt.json", {"crtfc_key": "invalid_key_000", "corp_code": "00000000",
                                                   "bsns_year": "2025", "reprt_code": "11011"})
    check("잘못된 인증키 → DartError", False, "(예외 미발생 — 네트워크 없으면 무시)")
except dart_svc.DartError as e:
    check("잘못된 인증키 → DartError", True)
    print(f"         메시지: {e}")
except Exception as e:
    print(f"  [SKIP] 네트워크 불가로 실제 호출 테스트 생략: {type(e).__name__}")

print()
print(f"결과: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
