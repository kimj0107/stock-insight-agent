# Stock Insight Agent

[![CI](https://github.com/kimj0107/stock-insight-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kimj0107/stock-insight-agent/actions/workflows/ci.yml)

주식 가격 변동의 **원인**을 AI가 분석해주는 에이전트.
종목 코드를 입력하면 Claude 에이전트가 최근 시세 변동과 관련 뉴스를 직접 수집(tool use)해
"왜 움직였는가"를 근거와 함께 설명합니다. *(투자 권유가 아닌 원인 설명입니다.)*

## 동작 방식

```
사용자 ──ticker──▶ FastAPI ──▶ StockInsightAgent (Claude, claude-opus-4-8)
                                      │  adaptive thinking + tool use loop
                                      ├─▶ get_recent_move / get_price_history (yfinance)
                                      └─▶ get_recent_news (NewsAPI → yfinance 폴백)
                                      ▼
                              근거 기반 변동 원인 분석
```

- **시세/뉴스 수집**: 에이전트가 필요한 데이터를 tool로 호출해 가져옵니다.
- **근거 기반**: tool이 반환한 데이터에만 근거하며, 부족하면 그렇게 밝히도록 지시되어 있습니다.

## 기술 스택

Python 3.11 · `anthropic` (claude-opus-4-8) · `yfinance` · `requests` · `fastapi` + `uvicorn` · `pytest`

## 빠른 시작

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # ANTHROPIC_API_KEY 입력
uvicorn main:app --reload     # 또는 python main.py
```

분석 요청:

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL"}'
```

응답 예시:

```json
{ "ticker": "AAPL", "analysis": "최근 5거래일 +7.8% ... (근거 포함 설명)" }
```

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /analyze` | `{"ticker": "...", "question": "(선택)"}` → 변동 원인 분석 |
| `GET /health` | 상태 및 사용 모델 확인 |

## CLI 사용법

서버 없이 터미널/단축키로 빠르게 분석할 때 (`cli.py`):

```bash
python cli.py TSLA              # 인자로 티커 전달
echo "TSLA" | python cli.py    # stdin 으로 전달 (크롬에서 선택 텍스트 파이프 등)
python cli.py TSLA --notify     # 한 줄 요약을 macOS 알림으로 표시
python cli.py TSLA --popup      # 핵심 발췌를 macOS 팝업 창으로 표시
python cli.py TSLA --notify --popup   # 둘 다 (독립적으로 동작)
python cli.py TSLA -q "어제 급락 원인은?"   # 추가 질문
```

- 입력에서 티커만 추출합니다 (공백/줄바꿈 제거, 대문자 변환).
- 결과는 한국어로 stdout에 출력됩니다.
- `ANTHROPIC_API_KEY` 가 없으면 안내 메시지를 출력하고 종료합니다.

## 환경 변수

`.env.example` 참고. 핵심:

- `ANTHROPIC_API_KEY` (필수)
- `ANTHROPIC_MODEL` (기본 `claude-opus-4-8`)
- `NEWS_API_KEY` (선택 — 없으면 yfinance 뉴스로 폴백)

## 테스트

```bash
pip install -r requirements-dev.txt
pytest
```

`tools/` 계층 단위 테스트로, 네트워크 호출은 모킹되어 외부 의존성 없이 실행됩니다.
`main`에 대한 push/PR마다 [GitHub Actions](.github/workflows/ci.yml)가 자동으로 `pytest`를 돌립니다.

## 프로젝트 구조

자세한 설계와 각 파일 역할은 [CLAUDE.md](CLAUDE.md)를 참고하세요.

```
agents/   Claude 에이전트 (tool use 루프 + 시스템 프롬프트)
tools/    시세/뉴스 데이터 계층 (순수 함수)
tests/    pytest 단위 테스트
main.py   FastAPI 앱
```

## 면책

이 프로젝트의 출력은 가격 변동에 대한 정보성 설명이며, 투자 자문이나 매매 권유가 아닙니다.
