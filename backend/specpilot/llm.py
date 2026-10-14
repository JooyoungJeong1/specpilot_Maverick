"""LLM 호출. 실제 API(AnthropicLLM)와 테스트용(ScriptedLLM)이 같은 모양을 가진다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)


class LLM(Protocol):
    def complete(self, system: str, messages: list[dict], max_tokens: int) -> LLMResult: ...


class AnthropicLLM:
    def __init__(self, model: str, thinking: str = "adaptive", effort: str = ""):
        import anthropic  # API 키 없이 테스트만 돌릴 때는 불러오지 않는다

        # ANTHROPIC_API_KEY 환경 변수를 쓴다. 과부하·일시적 네트워크 오류는 SDK가 기다렸다가 4번까지 다시 보낸다.
        self.client = anthropic.Anthropic(max_retries=4)
        self.model = model
        # SDK 버전에 따라 thinking·output_config 인자를 모를 수 있어서 요청 본문에 직접 넣는다.
        self.extra_body: dict = {}
        if thinking in ("adaptive", "disabled"):
            self.extra_body["thinking"] = {"type": thinking}
        if effort and thinking != "disabled":
            self.extra_body["output_config"] = {"effort": effort}

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> LLMResult:
        # 고정 부분(system)에 캐시를 걸어, 화면마다 반복되는 긴 지침을 매번 새로 읽지 않게 한다.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            extra_body=self.extra_body or None,
        ) as stream:
            msg = stream.get_final_message()
        # 생각(thinking) 블록은 결과에서 빼고 답(text)만 쓴다.
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        u = msg.usage
        details = getattr(u, "output_tokens_details", None)
        thinking_tokens = getattr(details, "thinking_tokens", None) if details is not None else None
        if thinking_tokens is None and isinstance(details, dict):
            thinking_tokens = details.get("thinking_tokens")
        usage = {
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "thinking_tokens": thinking_tokens or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        return LLMResult(text=text, stop_reason=msg.stop_reason, usage=usage)


class ScriptedLLM:
    """정해 둔 응답을 차례로 돌려준다. 테스트와 연습용."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, system: str, messages: list[dict], max_tokens: int) -> LLMResult:
        self.calls.append({"system": system, "messages": messages})
        if not self.responses:
            raise RuntimeError("ScriptedLLM: 준비된 응답이 더 없습니다")
        return LLMResult(text=self.responses.pop(0), stop_reason="end_turn")


class JSONParseError(ValueError):
    pass


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


def parse_json(text: str) -> dict:
    """응답에서 JSON 객체 하나를 꺼낸다. 코드 펜스나 앞뒤 설명이 붙어도 바깥 중괄호를 찾아 읽는다."""
    s = _FENCE.sub("", text.strip())
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise JSONParseError("응답에서 JSON 객체를 찾지 못했습니다")
    try:
        obj = json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise JSONParseError(f"JSON 문법 오류: {e.msg} (줄 {e.lineno}, 칸 {e.colno})") from e
    if not isinstance(obj, dict):
        raise JSONParseError("최상위가 객체가 아닙니다")
    return obj
