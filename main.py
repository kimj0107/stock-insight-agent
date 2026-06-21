"""FastAPI 진입점.

POST /analyze 로 종목 코드를 보내면 에이전트가 변동 원인을 분석해 반환한다.
실행: uvicorn main:app --reload
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel

from agents import StockInsightAgent

load_dotenv()

app = FastAPI(title="Stock Insight Agent", version="0.1.0")
_agent = StockInsightAgent()


class AnalyzeRequest(BaseModel):
    ticker: str
    question: str | None = None


class AnalyzeResponse(BaseModel):
    ticker: str
    analysis: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": _agent.model}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    analysis = _agent.analyze(req.ticker, req.question)
    return AnalyzeResponse(ticker=req.ticker, analysis=analysis)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
