"""요청별 예상 비용 (USD).

API 응답의 usage(입력·출력·캐시 쓰기·캐시 읽기 토큰)에 모델 가격을 곱한다. 생각(thinking) 토큰은 출력 토큰에 들어 있어
출력 가격으로 계산된다. 가격은 Claude API 공식 가격표(https://platform.claude.com/docs/en/about-claude/pricing,
2026-11 확인)의 100만 토큰당 달러이고, 캐시 쓰기는 5분 캐시 가격이다(llm.py가 ephemeral 캐시를 쓴다).

가격표에 없는 모델이나 가격이 바뀌었을 때는 .env의 SPECPILOT_PRICE에 "입력,출력,캐시쓰기,캐시읽기"를 넣는다.
예: SPECPILOT_PRICE=2,10,2.5,0.2
"""
from __future__ import annotations

import os

# 모델 이름 앞부분 → (입력, 출력, 캐시 쓰기 5분, 캐시 읽기)  단위: 100만 토큰당 USD
# 긴 이름을 먼저 맞춘다 (claude-sonnet-5-5가 claude-sonnet-5에 걸리지 않게).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-2": (8, 40, 10, 0.20),
    "claude-mythos-5-2": (8, 40, 10, 0.20),
    "claude-opus-5-5": (4, 20, 5, 0.20),
    "claude-opus-5": (5, 25, 6.25, 0.50),
    "claude-sonnet-5-5": (2, 10, 2.50, 0.10),
    "claude-sonnet-5": (2, 10, 2.50, 0.20),
    "claude-sonnet-4": (3, 15, 3.75, 0.30),
    "claude-haiku-4-5": (1, 5, 1.25, 0.10),
}
# Haiku 5.5는 요청의 입력(캐시 포함)이 10만 토큰을 넘으면 비싼 가격이 붙는다.
HAIKU_5_5 = ((0.10, 0.50, 0.125, 0.01), (0.50, 2.50, 0.625, 0.05), 100_000)


def price_for(model: str, prompt_tokens: int = 0) -> tuple[float, float, float, float] | None:
    env = os.getenv("SPECPILOT_PRICE", "").strip()
    if env:
        try:
            vals = tuple(float(x) for x in env.split(","))
            if len(vals) == 4:
                return vals          # type: ignore[return-value]
        except ValueError:
            pass
    m = (model or "").lower()
    if m.startswith("claude-haiku-5-5"):
        low, high, limit = HAIKU_5_5
        return high if prompt_tokens > limit else low
    for prefix in sorted(PRICES, key=len, reverse=True):
        if m.startswith(prefix):
            return PRICES[prefix]
    return None


def estimate(model: str, usage: dict) -> float | None:
    """호출 한 번의 usage로 예상 비용(USD). 가격을 모르면 None."""
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    cr = usage.get("cache_read_input_tokens", 0) or 0
    p = price_for(model, inp + cw + cr)
    if p is None:
        return None
    return round((inp * p[0] + out * p[1] + cw * p[2] + cr * p[3]) / 1_000_000, 6)
