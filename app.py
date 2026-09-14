"""DART × SAP × RCM — Internal Control Review Agent (교육용 데모).

철학:
  외부 데이터 자동 수집 → 사내 데이터 연결 → deterministic 검증 → 예외 탐지
  → AI 가 예외를 해석 → 사람이 최종 판단

숫자 검증은 시스템(Python)이, 예외 해석은 AI 가, 최종 판단은 사람이 한다.
"""

import html as html_lib
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from services import dart as dart_svc
from services import ai_review as ai_svc
from services import google_sheets as export_svc
from services import reconciliation as recon_svc
from services.reconciliation import (
    STATUS_CHECK,
    STATUS_MISSING,
    STATUS_NO_CONTROL,
    STATUS_OK,
)

load_dotenv(Path(__file__).resolve().parent / ".env")

# Streamlit Community Cloud 등에서는 .env 대신 st.secrets 로 키가 주입된다.
# os.getenv 기반 서비스 모듈들이 그대로 동작하도록 secrets 를 환경변수로 복사한다.
import os  # noqa: E402

try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:
    pass  # secrets 미설정 환경 (로컬 .env 사용)

st.set_page_config(page_title="Internal Control Review Agent", page_icon="⚖️", layout="wide")

# ---------------------------------------------------------------------------
# Linear 스타일 SaaS 테마 (Inter 폰트 · 카드 · pill 배지 · 미니멀 컬러)
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="st-"], [data-testid="stAppViewContainer"] * {
  font-family: 'Inter', 'Pretendard', -apple-system, 'Segoe UI', 'Malgun Gothic', sans-serif;
}
/* Material 아이콘 폰트는 오버라이드에서 제외 (아이콘이 텍스트로 보이는 것 방지) */
[data-testid="stIconMaterial"], [class*="material-symbols"] {
  font-family: 'Material Symbols Rounded' !important;
}
[data-testid="stAppViewContainer"] { background: #F7F7F8; }
[data-testid="stHeader"] { background: transparent; }
#MainMenu, footer { visibility: hidden; }
.block-container { padding-top: 1.6rem; padding-bottom: 4rem; max-width: 1180px; }

/* ---------- 상단 프로덕트 바 ---------- */
.topbar { display:flex; align-items:center; gap:14px; padding: 4px 2px 18px 2px;
  border-bottom: 1px solid #E9E9EC; margin-bottom: 26px; }
.logo-mark { width:38px; height:38px; border-radius:10px; flex:none;
  background: linear-gradient(135deg,#5E6AD2 0%,#8B5CF6 100%);
  display:flex; align-items:center; justify-content:center;
  color:#fff; font-weight:700; font-size:15px; letter-spacing:-0.5px;
  box-shadow: 0 2px 8px rgba(94,106,210,.35); }
.prod-name { font-size:16px; font-weight:700; color:#18181B; letter-spacing:-0.02em; line-height:1.2; }
.prod-sub { font-size:12.5px; color:#71717A; margin-top:1px; }
.topbar-right { margin-left:auto; display:flex; gap:8px; align-items:center; }
.chip { font-size:11.5px; font-weight:500; color:#52525B; background:#fff;
  border:1px solid #E4E4E7; border-radius:999px; padding:4px 12px; }
.chip.brand { color:#5E6AD2; background:#EEF0FB; border-color:#DDE1F7; }
.flow-strip { display:flex; flex-wrap:wrap; gap:6px; align-items:center;
  font-size:12px; color:#A1A1AA; margin: -12px 0 26px 2px; }
.flow-strip b { color:#52525B; font-weight:500; }
.flow-strip .arr { color:#D4D4D8; }

/* ---------- 스텝 카드 ---------- */
div[data-testid="stVerticalBlockBorderWrapper"] {
  background:#FFFFFF; border:1px solid #E4E4E7 !important; border-radius:14px;
  box-shadow: 0 1px 2px rgba(0,0,0,.03), 0 1px 6px rgba(0,0,0,.02);
  padding: 6px 10px; }
.step-head { display:flex; align-items:center; gap:12px; margin: 6px 0 4px 0; }
.step-num { width:26px; height:26px; border-radius:8px; flex:none;
  background:#EEF0FB; color:#5E6AD2; font-size:13px; font-weight:700;
  display:flex; align-items:center; justify-content:center; }
.step-title { font-size:15.5px; font-weight:600; color:#18181B; letter-spacing:-0.01em; }
.step-desc { font-size:12.5px; color:#71717A; margin-top:0px; }

/* ---------- 버튼 ---------- */
.stButton button, .stDownloadButton button {
  border-radius:8px; font-weight:500; font-size:13.5px;
  border:1px solid #E4E4E7; box-shadow:0 1px 2px rgba(0,0,0,.04); }
.stButton button[kind="primary"] {
  background:#5E6AD2; border-color:#5E6AD2; box-shadow:0 1px 3px rgba(94,106,210,.4); }
.stButton button[kind="primary"]:hover { background:#6E79DB; border-color:#6E79DB; }
.stButton button[kind="secondary"], .stDownloadButton button { background:#fff; color:#3F3F46; }
.stButton button[kind="secondary"]:hover, .stDownloadButton button:hover {
  background:#FAFAFA; border-color:#D4D4D8; color:#18181B; }

/* ---------- 입력/업로더 ---------- */
[data-testid="stFileUploaderDropzone"] {
  background:#FAFAFA; border:1.5px dashed #E4E4E7; border-radius:10px; }
[data-testid="stTextInput"] input, [data-testid="stSelectbox"] > div > div {
  border-radius:8px; }
[data-testid="stWidgetLabel"] p { font-size:12.5px; font-weight:500; color:#52525B; }

/* ---------- KPI 카드 ---------- */
.kpi-row { display:flex; gap:12px; flex-wrap:wrap; margin: 10px 0 18px 0; }
.kpi { flex:1; min-width:118px; background:#fff; border:1px solid #E4E4E7;
  border-radius:12px; padding:12px 14px 10px 14px;
  box-shadow:0 1px 2px rgba(0,0,0,.03); }
.kpi-label { display:flex; align-items:center; gap:7px; font-size:12px;
  font-weight:500; color:#71717A; }
.kpi .dot { width:8px; height:8px; border-radius:999px; flex:none; }
.kpi-val { font-size:26px; font-weight:700; color:#18181B; margin-top:6px;
  letter-spacing:-0.03em; font-variant-numeric: tabular-nums; }
.kpi-unit { font-size:13px; font-weight:500; color:#A1A1AA; margin-left:3px; }

/* ---------- 결과 테이블 ---------- */
.tbl-wrap { background:#fff; border:1px solid #E4E4E7; border-radius:12px;
  overflow:auto; box-shadow:0 1px 2px rgba(0,0,0,.03); margin-bottom: 6px; }
table.lin-tbl { width:100%; border-collapse:collapse; font-size:13px; }
table.lin-tbl th { text-align:left; font-size:11px; font-weight:600; color:#71717A;
  text-transform:uppercase; letter-spacing:.06em; padding:9px 13px;
  border-bottom:1px solid #E9E9EC; background:#FAFAFB; white-space:nowrap; }
table.lin-tbl td { padding:10px 13px; border-bottom:1px solid #F4F4F5;
  color:#3F3F46; white-space:nowrap; }
table.lin-tbl tr:last-child td { border-bottom:none; }
table.lin-tbl tr:hover td { background:#FAFAFB; }
table.lin-tbl td.num, table.lin-tbl th.num { text-align:right;
  font-variant-numeric: tabular-nums; }
table.lin-tbl td.acct { font-weight:600; color:#18181B; }
table.lin-tbl td.mono { color:#71717A; font-size:12.5px; }
.neg { color:#DC2626; }
.pos { color:#3F3F46; }

/* ---------- 상태 pill ---------- */
.pill { display:inline-flex; align-items:center; gap:6px; font-size:12px;
  font-weight:500; border-radius:999px; padding:3px 11px 3px 9px; white-space:nowrap; }
.pill .d { width:6px; height:6px; border-radius:999px; }
.pill.ok   { background:#ECFDF5; color:#047857; } .pill.ok .d { background:#10B981; }
.pill.warn { background:#FFF7ED; color:#C2410C; } .pill.warn .d { background:#F97316; }
.pill.err  { background:#FEF2F2; color:#B91C1C; } .pill.err .d { background:#EF4444; }
.pill.mut  { background:#F4F4F5; color:#52525B; } .pill.mut .d { background:#A1A1AA; }

/* ---------- AI 리뷰 ---------- */
div[data-testid="stExpander"] { background:#fff; border:1px solid #E4E4E7;
  border-radius:12px; box-shadow:0 1px 2px rgba(0,0,0,.03); }
div[data-testid="stExpander"] summary { font-weight:600; font-size:13.5px; }
div[data-testid="stExpander"] summary:hover { color:#5E6AD2; }
.review-body { font-size:13px; line-height:1.8; color:#3F3F46;
  background:#FAFAFB; border:1px solid #F0F0F2;
  border-radius:10px; padding:14px 18px; }
.review-body b { color:#18181B; font-weight:600; }
.review-meta { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }

/* ---------- 섹션 소제목 ---------- */
.sec-title { font-size:14px; font-weight:600; color:#18181B; margin:6px 0 2px 0; }
.sec-desc { font-size:12.5px; color:#71717A; margin-bottom:10px; }
.footnote { font-size:12px; color:#A1A1AA; line-height:1.7; }
.footnote b { color:#71717A; font-weight:600; }

hr { margin:1.4rem 0; border-color:#E9E9EC; }
[data-testid="stMetric"] { display:none; }
</style>
""",
    unsafe_allow_html=True,
)

PILL_CLASS = {
    STATUS_OK: "ok",
    STATUS_CHECK: "warn",
    STATUS_MISSING: "err",
    STATUS_NO_CONTROL: "mut",
}

# ---------------------------------------------------------------------------
# 세션 상태
# ---------------------------------------------------------------------------
for key, default in {
    "dart_df": None,
    "dart_source": "",       # "API" | "샘플"
    "company_name": "",
    "corp_code": "",
    "bsns_year": "2025",
    "sap_df": None,
    "rcm_df": None,
    "recon": None,
    "ai_reviews": {},        # account_name -> {"provider","text","fallback_reason"}
    "search_results": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


def fmt_num(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{int(v):,}"


def step_header(n: int, title: str, desc: str = ""):
    st.markdown(
        f'<div class="step-head"><span class="step-num">{n}</span>'
        f'<div><div class="step-title">{title}</div>'
        + (f'<div class="step-desc">{desc}</div>' if desc else "")
        + "</div></div>",
        unsafe_allow_html=True,
    )


def review_html(text: str) -> str:
    """AI 의견 텍스트를 markdown 재해석 없이 안전한 HTML 로 변환."""
    esc = html_lib.escape(text)
    for h in ("가능한 원인", "추가 확인 자료", "담당자 확인 질문", "평가의견 초안"):
        esc = esc.replace(h, f"<b>{h}</b>")
    return esc.replace("\n", "<br/>")


def pill(status: str) -> str:
    return f'<span class="pill {PILL_CLASS.get(status, "mut")}"><span class="d"></span>{status}</span>'


def result_table_html(view: pd.DataFrame) -> str:
    rows = []
    for _, r in view.iterrows():
        diff = r["diff"]
        diff_cls = "neg" if pd.notna(diff) and diff != 0 else "pos"
        diff_pct = f"{r['diff_pct']:g}%" if pd.notna(r["diff_pct"]) else "—"
        rows.append(
            "<tr>"
            f'<td class="acct">{html_lib.escape(str(r["account_name"]))}</td>'
            f"<td>{pill(r['status'])}</td>"
            f'<td class="num">{fmt_num(r["dart_amount"])}</td>'
            f'<td class="num">{fmt_num(r["sap_amount"])}</td>'
            f'<td class="num {diff_cls}">{fmt_num(diff)}</td>'
            f'<td class="num">{diff_pct}</td>'
            f'<td class="mono">{html_lib.escape(str(r["control_id"])) or "—"}</td>'
            f'<td class="num mono">{fmt_num(r["tolerance"])}</td>'
            "</tr>"
        )
    return (
        '<div class="tbl-wrap"><table class="lin-tbl">'
        "<thead><tr>"
        '<th>계정</th><th>상태</th><th class="num">DART</th><th class="num">SAP</th>'
        '<th class="num">차이</th><th class="num">차이율</th>'
        '<th>RCM</th><th class="num">허용오차</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def kpi_cards_html(kpi: dict) -> str:
    items = [
        ("전체 검토", kpi["total"], "#5E6AD2"),
        ("정상", kpi[STATUS_OK], "#10B981"),
        ("확인 필요", kpi[STATUS_CHECK], "#F97316"),
        ("데이터 누락", kpi[STATUS_MISSING], "#EF4444"),
        ("통제 매핑 필요", kpi[STATUS_NO_CONTROL], "#A1A1AA"),
    ]
    cards = "".join(
        f'<div class="kpi"><div class="kpi-label"><span class="dot" style="background:{c}"></span>{label}</div>'
        f'<div class="kpi-val">{v}<span class="kpi-unit">건</span></div></div>'
        for label, v, c in items
    )
    return f'<div class="kpi-row">{cards}</div>'


# ---------------------------------------------------------------------------
# 상단 프로덕트 바
# ---------------------------------------------------------------------------
api_key = dart_svc.get_api_key()
provider = ai_svc.active_provider()

st.markdown(
    f"""
<div class="topbar">
  <div class="logo-mark">IC</div>
  <div>
    <div class="prod-name">DART × SAP × RCM</div>
    <div class="prod-sub">Internal Control Review Agent</div>
  </div>
  <div class="topbar-right">
    <span class="chip">DART API {'● 연결됨' if api_key else '○ 미설정'}</span>
    <span class="chip">AI · {provider}</span>
    <span class="chip brand">Demo</span>
  </div>
</div>
<div class="flow-strip">
  <b>외부 데이터 수집</b><span class="arr">→</span><b>사내 데이터 연결</b><span class="arr">→</span>
  <b>기준 기반 검증</b>(시스템)<span class="arr">→</span><b>예외 탐지</b><span class="arr">→</span>
  <b>AI 해석</b><span class="arr">→</span><b>사람의 최종 판단</b>
</div>
""",
    unsafe_allow_html=True,
)

# ===========================================================================
# STEP 1. DART 데이터 가져오기
# ===========================================================================
with st.container(border=True):
    step_header(1, "DART 재무정보 가져오기", "OpenDART 전자공시 API에서 주요 재무계정을 자동 수집합니다")

    if not api_key:
        st.warning(
            "OpenDART API Key 가 설정되어 있지 않습니다. `.env` 파일에 `DART_API_KEY=발급받은키` 를 입력하세요. "
            "키가 없어도 아래 **샘플 DART 데이터**로 전체 흐름을 시연할 수 있습니다.",
            icon="🔑",
        )

    col1, col2, col3, col4 = st.columns([2.2, 1, 1.2, 1.4])
    with col1:
        company_query = st.text_input("회사명 검색", value="JYP Ent.", placeholder="예: JYP Ent.")
    with col2:
        year = st.selectbox("사업연도", [str(y) for y in range(2026, 2015, -1)], index=1)
    with col3:
        report_name = st.selectbox("보고서 종류", list(dart_svc.REPORT_CODES.keys()))
    with col4:
        fs_name = st.selectbox("재무제표 구분", list(dart_svc.FS_DIVS.keys()))

    # --- 회사 검색 ---
    if api_key:
        if st.button("회사 검색", type="secondary"):
            try:
                with st.spinner("DART 고유번호 목록 조회 중... (최초 1회는 수십 초 걸릴 수 있습니다)"):
                    st.session_state.search_results = dart_svc.search_company(api_key, company_query)
            except dart_svc.DartError as e:
                st.error(f"회사 검색 실패: {e}")

        results = st.session_state.search_results
        if results is not None and len(results) > 0:
            options = {
                f"{r.corp_name}  ({'상장 ' + r.stock_code if r.stock_code else '비상장'} / corp_code {r.corp_code})": r.corp_code
                for r in results.itertuples()
            }
            picked = st.selectbox("검색 결과에서 회사 선택", list(options.keys()))
            st.session_state.corp_code = options[picked]
            st.session_state.company_name = picked.split("  (")[0]
        elif results is not None:
            st.info("검색 결과가 없습니다. 회사명을 다시 확인하세요.")

        corp_code_input = st.text_input(
            "corp_code 직접 입력 (선택)",
            value=st.session_state.corp_code,
            help="8자리 DART 고유번호. 회사 검색을 사용하면 자동 입력됩니다.",
        )
        if corp_code_input.strip():
            st.session_state.corp_code = corp_code_input.strip()

    b1, b2, _sp = st.columns([1.7, 2.1, 1.2])
    with b1:
        fetch_clicked = st.button("📥 DART 재무정보 가져오기", type="primary", disabled=not api_key)
    with b2:
        sample_clicked = st.button("🧪 샘플 DART 데이터 사용 (오프라인 데모)")

    if fetch_clicked:
        if not st.session_state.corp_code:
            st.error("corp_code 가 없습니다. 먼저 [회사 검색] 으로 회사를 선택하거나 corp_code 를 직접 입력하세요.")
        else:
            try:
                with st.spinner("OpenDART 주요계정 조회 중..."):
                    df = dart_svc.fetch_financials(
                        api_key,
                        st.session_state.corp_code,
                        year,
                        dart_svc.REPORT_CODES[report_name],
                        dart_svc.FS_DIVS[fs_name],
                    )
                st.session_state.dart_df = df
                st.session_state.dart_source = "API"
                st.session_state.bsns_year = year
                if not st.session_state.company_name:
                    st.session_state.company_name = company_query
                st.session_state.recon = None
                st.session_state.ai_reviews = {}
                st.success(
                    f"DART 조회 완료: {len(df)}개 계정 (재무제표 구분: {df.attrs.get('fs_div_used', '')})"
                )
            except dart_svc.DartError as e:
                st.error(f"DART 조회 실패: {e}")
            except Exception as e:
                st.error(f"예상치 못한 오류가 발생했습니다: {e}")

    if sample_clicked:
        st.session_state.dart_df = dart_svc.sample_financials()
        st.session_state.dart_source = "샘플"
        st.session_state.company_name = st.session_state.company_name or company_query or "JYP Ent.(샘플)"
        st.session_state.bsns_year = year
        st.session_state.recon = None
        st.session_state.ai_reviews = {}
        st.success(f"샘플 DART 데이터를 불러왔습니다 ({len(st.session_state.dart_df)}개 계정).")

    if st.session_state.dart_df is not None:
        df = st.session_state.dart_df
        st.markdown(
            f'<div class="review-meta">'
            f'<span class="chip">출처 · {st.session_state.dart_source}</span>'
            f'<span class="chip">{html_lib.escape(st.session_state.company_name)}</span>'
            f'<span class="chip">{st.session_state.bsns_year}년</span>'
            f'<span class="chip">{len(df)}개 계정</span></div>',
            unsafe_allow_html=True,
        )
        dart_view = pd.DataFrame(
            {
                "account_name": df["account_name"],
                "dart_amount": df["amount"],
                "sap_amount": None,
                "diff": None,
                "diff_pct": None,
                "control_id": df["sj_div"],
                "tolerance": None,
                "status": "",
            }
        )
        # DART 미리보기는 간단 테이블로
        rows = "".join(
            f'<tr><td class="acct">{html_lib.escape(str(r["account_name"]))}</td>'
            f'<td class="num">{fmt_num(r["amount"])}</td>'
            f'<td class="mono">{r["sj_div"]}</td>'
            f'<td class="mono">{html_lib.escape(str(r.get("fs_nm", "")))}</td></tr>'
            for _, r in df.iterrows()
        )
        st.markdown(
            '<div class="tbl-wrap"><table class="lin-tbl"><thead><tr>'
            '<th>계정명</th><th class="num">당기금액</th><th>구분</th><th>재무제표</th>'
            f"</tr></thead><tbody>{rows}</tbody></table></div>",
            unsafe_allow_html=True,
        )

        st.download_button(
            "⬇️ 현재 DART 숫자 기준 데모용 SAP 샘플 CSV 생성",
            data=recon_svc.generate_demo_sap_csv(df),
            file_name="sap_trial_balance_demo.csv",
            mime="text/csv",
            help="실제 조회된 DART 금액을 기준으로 일치/오차이내/오차초과/누락 시나리오가 섞인 SAP 시산표를 생성합니다. 실 데이터 시연용.",
        )

st.write("")

# ===========================================================================
# STEP 2. SAP 시산표 / RCM 업로드
# ===========================================================================
with st.container(border=True):
    step_header(2, "SAP 시산표 · RCM 통제기준 연결", "사내 데이터를 업로드하여 공시 데이터와 결합합니다")

    c_sap, c_rcm = st.columns(2)

    with c_sap:
        st.markdown('<div class="sec-title">SAP 시산표</div><div class="sec-desc">CSV/XLSX · 컬럼: account_code, account_name, amount</div>', unsafe_allow_html=True)
        sap_file = st.file_uploader("SAP 파일", type=["csv", "xlsx", "xls"], key="sap_upload", label_visibility="collapsed")
        if sap_file is not None:
            try:
                st.session_state.sap_df = recon_svc.load_sap_file(sap_file, sap_file.name)
                st.session_state.recon = None
            except recon_svc.FileFormatError as e:
                st.session_state.sap_df = None
                st.error(f"SAP 파일 오류: {e}")
        if st.button("샘플 SAP 시산표 사용"):
            with open(SAMPLES_DIR / "sap_trial_balance.csv", "rb") as f:
                st.session_state.sap_df = recon_svc.load_sap_file(f, "sap_trial_balance.csv")
            st.session_state.recon = None
        if st.session_state.sap_df is not None:
            rows = "".join(
                f'<tr><td class="mono">{html_lib.escape(str(r.get("account_code", "")))}</td>'
                f'<td class="acct">{html_lib.escape(str(r["account_name"]))}</td>'
                f'<td class="num">{fmt_num(r["amount"])}</td></tr>'
                for _, r in st.session_state.sap_df.iterrows()
            )
            st.markdown(
                '<div class="tbl-wrap" style="max-height:250px"><table class="lin-tbl"><thead><tr>'
                '<th>계정코드</th><th>계정명</th><th class="num">금액</th>'
                f"</tr></thead><tbody>{rows}</tbody></table></div>",
                unsafe_allow_html=True,
            )

    with c_rcm:
        st.markdown('<div class="sec-title">RCM 통제기준</div><div class="sec-desc">CSV/XLSX · 컬럼: control_id, account_name, control_name, tolerance, required_evidence</div>', unsafe_allow_html=True)
        rcm_file = st.file_uploader("RCM 파일", type=["csv", "xlsx", "xls"], key="rcm_upload", label_visibility="collapsed")
        if rcm_file is not None:
            try:
                st.session_state.rcm_df = recon_svc.load_rcm_file(rcm_file, rcm_file.name)
                st.session_state.recon = None
            except recon_svc.FileFormatError as e:
                st.session_state.rcm_df = None
                st.error(f"RCM 파일 오류: {e}")
        if st.button("샘플 RCM 사용"):
            with open(SAMPLES_DIR / "rcm_controls.csv", "rb") as f:
                st.session_state.rcm_df = recon_svc.load_rcm_file(f, "rcm_controls.csv")
            st.session_state.recon = None
        if st.session_state.rcm_df is not None:
            rows = "".join(
                f'<tr><td class="mono">{html_lib.escape(str(r["control_id"]))}</td>'
                f'<td class="acct">{html_lib.escape(str(r["account_name"]))}</td>'
                f'<td>{html_lib.escape(str(r["control_name"]))}</td>'
                f'<td class="num">{fmt_num(r["tolerance"])}</td></tr>'
                for _, r in st.session_state.rcm_df.iterrows()
            )
            st.markdown(
                '<div class="tbl-wrap" style="max-height:250px"><table class="lin-tbl"><thead><tr>'
                '<th>통제 ID</th><th>계정명</th><th>통제명</th><th class="num">허용오차</th>'
                f"</tr></thead><tbody>{rows}</tbody></table></div>",
                unsafe_allow_html=True,
            )

st.write("")

# ===========================================================================
# STEP 3. 자동 대사 및 AI 검토
# ===========================================================================
with st.container(border=True):
    step_header(3, "자동 대사 · AI 검토 · 내보내기", "tolerance 기반 deterministic 판정 후, 예외 항목만 AI가 해석합니다")

    ready = st.session_state.dart_df is not None and st.session_state.sap_df is not None
    if not ready:
        st.info("Step 1 의 DART 데이터와 Step 2 의 SAP 시산표를 먼저 준비하세요. (RCM 은 선택 — 없으면 '통제 매핑 필요'로 표시됩니다)")

    if st.button("⚖️ 대사 및 검토 실행", type="primary", disabled=not ready):
        try:
            st.session_state.recon = recon_svc.reconcile(
                st.session_state.dart_df, st.session_state.sap_df, st.session_state.rcm_df
            )
            st.session_state.ai_reviews = {}
        except Exception as e:
            st.error(f"대사 실행 중 오류: {e}")

    recon = st.session_state.recon
    if recon is not None and len(recon) > 0:
        # --- KPI 카드 ---
        kpi = recon_svc.summarize(recon)
        st.markdown(kpi_cards_html(kpi), unsafe_allow_html=True)

        # --- 필터 ---
        filter_opts = ["전체", STATUS_CHECK, STATUS_MISSING, STATUS_NO_CONTROL, STATUS_OK]
        try:
            picked_filter = st.segmented_control(
                "상태 필터", filter_opts, default="전체", label_visibility="collapsed"
            ) or "전체"
        except Exception:
            picked_filter = st.radio("상태 필터", filter_opts, horizontal=True, label_visibility="collapsed")
        view = recon if picked_filter == "전체" else recon[recon["status"] == picked_filter]

        # --- 결과 테이블 (pill 배지) ---
        st.markdown(result_table_html(view), unsafe_allow_html=True)

        # ------------------------------------------------------------------
        # AI 검토의견
        # ------------------------------------------------------------------
        exceptions = recon_svc.exceptions_only(recon)
        st.markdown('<div class="sec-title" style="margin-top:18px">AI 검토의견</div>', unsafe_allow_html=True)
        provider = ai_svc.active_provider()
        st.markdown(
            f'<div class="sec-desc">예외 항목 <b>{len(exceptions)}건</b>만 AI에게 전달됩니다 (정상 항목은 전달하지 않음) · '
            f'현재 provider: <b>{provider}</b>'
            + (" — API Key 미설정으로 규칙 기반 mock 사용" if provider == "mock" else "")
            + "</div>",
            unsafe_allow_html=True,
        )

        if len(exceptions) == 0:
            st.success("예외 항목이 없습니다. AI 검토가 필요하지 않습니다.")
        elif st.button("🤖 AI 검토의견 생성"):
            reviews = {}
            progress = st.progress(0.0)
            for i, (_, row) in enumerate(exceptions.iterrows()):
                ctx = {
                    "company": st.session_state.company_name,
                    "year": st.session_state.bsns_year,
                    "account_name": row["account_name"],
                    "status": row["status"],
                    "dart_amount": None if pd.isna(row["dart_amount"]) else int(row["dart_amount"]),
                    "sap_amount": None if pd.isna(row["sap_amount"]) else int(row["sap_amount"]),
                    "diff": None if pd.isna(row["diff"]) else int(row["diff"]),
                    "diff_pct": None if pd.isna(row["diff_pct"]) else float(row["diff_pct"]),
                    "control_id": row["control_id"],
                    "control_name": row["control_name"],
                    "tolerance": None if pd.isna(row["tolerance"]) else int(row["tolerance"]),
                    "required_evidence": row["required_evidence"],
                }
                reviews[row["account_name"]] = ai_svc.generate_review_comment(ctx)
                progress.progress((i + 1) / len(exceptions))
            progress.empty()
            st.session_state.ai_reviews = reviews

        if st.session_state.ai_reviews:
            for _, row in exceptions.iterrows():
                acct = row["account_name"]
                review = st.session_state.ai_reviews.get(acct)
                if not review:
                    continue
                label = f"{acct} · {row['control_id'] or '통제 없음'} — {row['status']}"
                with st.expander(label, expanded=True):
                    st.markdown(
                        f'<div class="review-meta">'
                        f'<span class="chip">DART {fmt_num(row["dart_amount"])}원</span>'
                        f'<span class="chip">SAP {fmt_num(row["sap_amount"])}원</span>'
                        f'<span class="chip">차이 {fmt_num(row["diff"])}원</span>'
                        f'<span class="chip brand">provider · {review["provider"]}</span>'
                        f"{pill(row['status'])}</div>",
                        unsafe_allow_html=True,
                    )
                    if review.get("fallback_reason"):
                        st.warning(review["fallback_reason"], icon="⚠️")
                    st.markdown(
                        f'<div class="review-body">{review_html(review["text"])}</div>',
                        unsafe_allow_html=True,
                    )
            st.markdown(
                '<div class="footnote">⚠️ AI 의견은 담당자의 검토가 필요한 <b>초안</b>입니다. 최종 판단은 사람이 합니다.</div>',
                unsafe_allow_html=True,
            )

        # ------------------------------------------------------------------
        # 내보내기
        # ------------------------------------------------------------------
        st.markdown('<div class="sec-title" style="margin-top:18px">결과 내보내기</div>', unsafe_allow_html=True)
        questions = {
            acct: ai_svc.extract_question(r["text"]) for acct, r in st.session_state.ai_reviews.items()
        }
        export_df = export_svc.build_export_df(
            recon,
            st.session_state.company_name,
            st.session_state.bsns_year,
            st.session_state.ai_reviews,
            questions,
        )

        e1, e2, e3, _sp = st.columns([1.4, 1, 1, 1.6])
        with e1:
            if export_svc.google_sheets_configured():
                if st.button("📊 Google Sheets로 내보내기", type="primary"):
                    try:
                        with st.spinner("Google Sheets 기록 중..."):
                            url = export_svc.export_to_google_sheets(export_df)
                        st.success("Google Sheets 기록 완료")
                        st.markdown(f"[▶ 시트 열기]({url})")
                    except Exception as e:
                        st.error(f"Google Sheets 기록 실패: {e} — 아래 XLSX/CSV 다운로드를 이용하세요.")
            else:
                st.button("📊 Google Sheets로 내보내기", disabled=True,
                          help="GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEET_ID 를 .env 에 설정하면 활성화됩니다.")
        with e2:
            st.download_button(
                "⬇️ XLSX 다운로드",
                data=export_svc.to_xlsx_bytes(export_df),
                file_name=f"내부회계검토결과_{st.session_state.bsns_year}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with e3:
            st.download_button(
                "⬇️ CSV 다운로드",
                data=export_svc.to_csv_bytes(export_df),
                file_name=f"내부회계검토결과_{st.session_state.bsns_year}.csv",
                mime="text/csv",
            )
        if not export_svc.google_sheets_configured():
            st.markdown('<div class="footnote">Google 인증정보 미설정 → XLSX/CSV 다운로드를 이용하세요.</div>', unsafe_allow_html=True)

st.markdown(
    '<div class="footnote" style="margin-top:26px; text-align:center;">'
    "이 데모의 핵심 — <b>AI가 숫자를 판단하는 시스템이 아니라, 시스템이 숫자를 검증하고 AI가 예외 해석을 보조하는 구조</b><br/>"
    "모든 금액 계산과 상태 판정은 deterministic Python 코드가 수행하며, AI는 예외 항목의 해석 초안만 작성합니다.</div>",
    unsafe_allow_html=True,
)
