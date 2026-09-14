# DART × SAP × RCM — Internal Control Review Agent

내부회계관리제도 업무 자동화 교육용 데모.

**DART 전자공시 데이터 + SAP 시산표 + RCM 통제기준**을 결합하여:

1. 계정별 숫자를 자동 대사하고
2. 불일치/예외 항목을 탐지하고
3. 관련 내부통제(RCM) 기준을 연결하고
4. AI가 확인사항 및 평가의견 **초안**을 작성하고
5. 결과를 Google Sheets / XLSX / CSV로 내보냅니다

## 핵심 철학

```text
외부 데이터 자동 수집 (OpenDART API)
        ↓
사내 데이터 연결 (SAP 시산표, RCM)
        ↓
기준에 따른 deterministic 검증 (Python — LLM 미사용)
        ↓
예외사항 탐지 (tolerance 기반)
        ↓
AI가 예외를 해석 (원인 가설 / 확인자료 / 질문 / 의견 초안)
        ↓
사람이 최종 판단
```

> **AI가 숫자를 판단하는 시스템이 아니라, 시스템이 숫자를 검증하고 AI가 예외 처리를 보조하는 구조**입니다.
> 모든 금액 계산과 상태 판정은 `services/reconciliation.py`의 Python 코드가 수행하며,
> AI는 예외 항목만 전달받아 해석 초안을 작성합니다.

---

## 1. 설치

### macOS / Linux

```bash
git clone <repo-url>
cd dart-sap-rcm-demo

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
```

### Windows (PowerShell)

```powershell
git clone <repo-url>
cd dart-sap-rcm-demo

python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

copy .env.example .env
```

> PowerShell에서 스크립트 실행이 막히면:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` 실행 후 다시 activate 하세요.
> CMD 사용자는 `.venv\Scripts\activate.bat` 를 실행하면 됩니다.

## 2. OpenDART API Key 설정 (필수)

1. https://opendart.fss.or.kr 접속 → **인증키 신청/관리** → 회원가입 후 API 인증키 발급 (무료, 즉시 발급)
2. 프로젝트 루트의 `.env` 파일을 열어 발급받은 40자리 키를 입력:

```env
DART_API_KEY=여기에_발급받은_인증키_입력
```

> **키가 없어도 데모는 가능합니다.** 앱 안의 `샘플 DART 데이터 사용 (오프라인 데모)` 버튼을 누르면
> 내장 샘플 데이터로 전체 워크플로우를 시연할 수 있습니다.

## 3. 실행

```bash
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 자동으로 열립니다.

## 4. 데모 진행 순서 (5분 시나리오)

| 순서 | 조작 | 보여줄 것 |
|---|---|---|
| 1 | 회사명 `JYP Ent.` → **회사 검색** → **DART 재무정보 가져오기** | 실제 전자공시 API 호출 |
| 2 | (오프라인 시) **샘플 DART 데이터 사용** | API 없이도 동일 흐름 |
| 3 | **샘플 SAP 시산표 사용** + **샘플 RCM 사용** | 사내 데이터 연결 |
| 4 | **대사 및 검토 실행** | KPI 카드 + 상태별 색상 테이블 |
| 5 | **AI 검토의견 생성** | 예외 항목만 AI에 전달됨을 강조 |
| 6 | **XLSX 다운로드** 또는 **Google Sheets로 내보내기** | 실무 산출물 |

실제 API 데이터로 시연할 때는 DART 조회 후
**"현재 DART 숫자 기준 데모용 SAP 샘플 CSV 생성"** 버튼으로
일치/오차이내/오차초과/누락 시나리오가 섞인 SAP 파일을 만들어 업로드하면 됩니다.

### 샘플 데이터에 포함된 시나리오

| 계정 | 시나리오 | 판정 |
|---|---|---|
| 영업이익, 자산총계, 부채총계, 자본총계 | 완전 일치 | 🟢 정상 |
| 당기순이익 | 차이 5백만원 (허용오차 1천만원 이내) | 🟢 정상 |
| 매출액 | 차이 5천만원 (허용오차 초과) | 🟠 확인 필요 |
| 유동자산 | DART에만 존재 | 🔴 데이터 누락 |
| 판매비와관리비 | SAP에만 존재 | 🔴 데이터 누락 |
| 매출원가 | RCM 통제 미정의 | ⚪ 통제 매핑 필요 |

## 5. AI Provider 설정 (선택)

`.env`에서 provider를 교체할 수 있습니다. **키가 없으면 자동으로 규칙 기반 mock으로 동작**하며 앱은 멈추지 않습니다.

```env
AI_PROVIDER=claude          # mock | claude | openai | gemini
ANTHROPIC_API_KEY=sk-ant-...
```

AI에게는 다음 안전 원칙이 시스템 프롬프트로 강제됩니다:
제공되지 않은 사실 추측 금지 · 근거 없으면 "확인 필요" 표시 · **숫자 재계산 금지(제공된 계산 결과만 사용)** · 회계/법률 최종 판단 금지 · 결과는 담당자 검토가 필요한 초안.

## 6. Google Sheets 내보내기 (선택)

1. Google Cloud Console에서 서비스 계정 생성 → JSON 키 다운로드
2. Google Sheets API + Drive API 활성화
3. 대상 스프레드시트를 서비스 계정 이메일(`...@...iam.gserviceaccount.com`)에 **편집자로 공유**
4. `.env` 설정:

```env
GOOGLE_SERVICE_ACCOUNT_JSON=C:\path\to\service_account.json
GOOGLE_SHEET_ID=스프레드시트URL의_d와_edit사이_문자열
```

미설정 시 버튼이 비활성화되고 XLSX/CSV 다운로드로 대체됩니다.

## 7. 테스트

외부 API 없이 핵심 로직(매핑·대사·판정·mock AI·내보내기)을 검증합니다:

```bash
python tests/test_core.py
```

## 프로젝트 구조

```text
dart-sap-rcm-demo/
├─ app.py                      # Streamlit UI (단일 화면 워크플로우)
├─ services/
│  ├─ dart.py                  # OpenDART API (corpCode 검색, fnlttSinglAcnt 주요계정)
│  ├─ reconciliation.py        # 대사 엔진 — 모든 숫자 계산/판정 (deterministic)
│  ├─ ai_review.py             # AI 검토의견 (provider 교체 + mock fallback)
│  └─ google_sheets.py         # Google Sheets / XLSX / CSV 내보내기
├─ data/
│  └─ account_mapping.py       # 계정명 alias 매핑
├─ samples/
│  ├─ sap_trial_balance.csv    # SAP 시산표 샘플 (예외 시나리오 포함)
│  └─ rcm_controls.csv         # RCM 통제기준 샘플
├─ tests/test_core.py
├─ .env.example
└─ requirements.txt
```

## 판정 규칙 (deterministic)

```text
차이 = SAP 금액 - DART 금액
차이율 = abs(차이) / abs(DART 금액) × 100

DART 또는 SAP 값 없음   → 데이터 누락
RCM 통제 없음           → 통제 매핑 필요
abs(차이) ≤ tolerance   → 정상
abs(차이) > tolerance   → 확인 필요
```

## 문제 해결

| 증상 | 해결 |
|---|---|
| `OpenDART 오류 [010]` | `.env`의 `DART_API_KEY` 오타 확인 |
| `OpenDART 오류 [013] 조회된 데이터가 없습니다` | 해당 연도 보고서가 아직 미제출 — 사업연도를 한 해 전으로 |
| 회사 검색이 오래 걸림 | 최초 1회 corpCode 전체 목록(약 10MB) 다운로드 — 이후 캐시 사용 |
| Google Sheets 실패 | 서비스 계정에 시트 공유 여부, API 활성화 여부 확인 |
| 한글 CSV 깨짐 | 다운로드 CSV는 utf-8-sig(BOM) — Excel에서 바로 열립니다 |
