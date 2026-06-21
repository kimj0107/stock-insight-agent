# 작업 규칙 (Working rules)

- **항상 영어로 답변한다.** 사용자와의 대화/응답은 영어로 작성한다.
- **코드 안의 한국어 문자열은 그대로 둔다.** 분석 출력 등 코드 내 한국어 문자열은
  사용자가 명시적으로 요청할 때만 변경한다.

---

# Stock Insight Agent

주식 가격 변동의 **원인**을 AI가 분석해주는 에이전트.
사용자가 종목 코드를 입력하면, 에이전트가 최근 시세 변동과 관련 뉴스를 직접 수집(tool use)해
"왜 움직였는가"를 근거와 함께 설명한다.

## 개요

- **입력**: 종목 코드(예: `AAPL`, `005930.KS`)와 선택적 질문.
- **처리**: Claude(`claude-opus-4-8`)가 adaptive thinking으로 추론하면서,
  필요한 데이터를 tool로 호출해 수집 → 종합 분석.
- **출력**: 가격 변동의 추정 원인 설명(투자 권유 아님).
- **인터페이스**: FastAPI REST (`POST /analyze`).

## 기술 스택

| 영역 | 기술 |
|------|------|
| 언어 | Python 3.11 |
| 패키지 관리 | pip (`requirements.txt`) |
| LLM | Anthropic Claude (`anthropic` SDK, 모델 `claude-opus-4-8`) |
| 시세 데이터 | `yfinance` |
| HTTP / 뉴스 | `requests` (NewsAPI), yfinance 뉴스 폴백 |
| 설정 | `python-dotenv` |
| API 서버 | `fastapi` + `uvicorn` |
| 테스트 | `pytest` (네트워크 모킹) |

## 파일 구조 및 역할

```
stock-insight-agent/
├── agents/
│   ├── __init__.py            # StockInsightAgent export
│   └── analysis_agent.py      # 핵심 에이전트: Claude 호출 + tool use 루프 + 시스템 프롬프트
├── tools/
│   ├── __init__.py            # 도구 함수 export
│   ├── stock_data.py          # yfinance 시세 조회 (get_price_history, get_recent_move)
│   └── news.py                # 뉴스 수집 (get_recent_news; NewsAPI → yfinance 폴백)
├── tests/
│   ├── __init__.py
│   └── test_tools.py          # tools 계층 단위 테스트 (외부 호출 모킹)
├── main.py                    # FastAPI 앱 (POST /analyze, GET /health)
├── requirements.txt           # 의존성
├── .env.example               # 필요한 환경변수 목록
├── .gitignore
└── CLAUDE.md                  # 이 문서
```

### 계층 설명

- **`tools/`** — 순수 데이터 계층. LLM 호출이나 해석 없이 시세/뉴스만 반환한다.
  에이전트의 tool 구현이자, 단독 테스트가 쉬운 함수들.
- **`agents/analysis_agent.py`** — 오케스트레이션 계층.
  - `TOOLS`: Anthropic Messages API용 tool 스키마.
  - `_DISPATCH`: tool 이름 → `tools/` 함수 매핑.
  - `StockInsightAgent.analyze()`: 수동 agentic loop —
    `stop_reason == "tool_use"`이면 도구를 실행해 결과를 다시 모델에 전달, 아니면 최종 답변 반환.
- **`main.py`** — 전송 계층. HTTP 요청을 에이전트 호출로 연결.

## 환경 변수

`.env.example`을 `.env`로 복사해 채운다. 주요 항목:

- `ANTHROPIC_API_KEY` (필수)
- `ANTHROPIC_MODEL` (기본 `claude-opus-4-8`)
- `NEWS_API_KEY` (선택 — 없으면 yfinance 뉴스로 폴백)
- `HOST`, `PORT`, `LOG_LEVEL`

## 실행

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 키 입력
uvicorn main:app --reload     # 또는 python main.py
```

분석 요청:

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'
```

테스트:

```bash
pytest
```

## 규칙 / 주의

- 에이전트는 **tool이 반환한 데이터에만 근거**해 분석한다 (시스템 프롬프트에 명시).
  근거가 부족하면 그렇게 말하도록 지시되어 있다.
- 출력은 변동 원인 설명이며 **투자 권유가 아니다.**
- 모델은 adaptive thinking(`thinking={"type": "adaptive"}`)을 사용한다.
  `budget_tokens`는 `claude-opus-4-8`에서 사용 불가(400).
- 새 도구를 추가할 때: `tools/`에 함수 작성 → `analysis_agent.py`의 `TOOLS` 스키마와
  `_DISPATCH`에 등록.
```
