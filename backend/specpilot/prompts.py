"""프롬프트 파일을 읽어 자리표시자({{NAME}})를 채운다.

프롬프트 문장은 전부 prompts/ 폴더의 파일에 있고, 코드는 자리만 채운다.
프롬프트를 고칠 때 코드를 건드릴 필요가 없게 하려는 것이다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
INPUT_HEADING = "\n# 입력"

TEMPLATES = {
    "app_profile": "app_profile.txt",
    "screen_decompose": "screen_decompose.txt",
    "judge": "judge.txt",
    "code_select": "code_select.txt",
}


@dataclass
class RenderedPrompt:
    name: str
    system: str       # 실행마다 같은 부분 (캐시 대상)
    user_input: str   # "# 입력" 이후, 실행마다 달라지는 부분
    version: str      # 고정 부분의 해시. 결과가 어떤 프롬프트로 나왔는지 기록용


class PromptSet:
    def __init__(self, prompts_dir: Path):
        self.dir = Path(prompts_dir)
        self.blocks = {
            "READING_GUIDE": self._read("blocks/reading_guide.txt"),
            "IMPLIED_RULE": self._read("blocks/implied_rule.txt"),
            "UNIT_SCHEMA": self._read("blocks/unit_schema.txt"),
            "APP_EXAMPLE": self._read("examples/app_example.json"),
            "SCREEN_EXAMPLE": self._read("examples/screen_example.json"),
            "SCREEN_EXAMPLE_2": self._read("examples/screen_example_2.json", required=False),
            "JUDGE_EXAMPLE": self._read("examples/judge_example.json", required=False),
            "HINTS": self._read("hints.txt", required=False) or "(없음)",
        }

    def _read(self, rel: str, required: bool = True) -> str:
        path = self.dir / rel
        if not path.exists():
            if required:
                raise FileNotFoundError(f"프롬프트 파일이 없습니다: {path}")
            return ""
        return path.read_text(encoding="utf-8").strip()

    def render(self, name: str, **values: str) -> RenderedPrompt:
        template = self._read(TEMPLATES[name])
        cut = template.rfind(INPUT_HEADING)
        if cut < 0:
            raise ValueError(f"{name}: '# 입력' 제목이 없어 고정 부분과 입력 부분을 나눌 수 없습니다")
        fixed, dynamic = template[:cut], template[cut + 1:]

        fixed_text = self._fill(fixed, self.blocks, name)
        dynamic_text = self._fill(dynamic, {**self.blocks, **values}, name)
        version = hashlib.sha256(fixed_text.encode("utf-8")).hexdigest()[:12]
        return RenderedPrompt(name, fixed_text.strip(), dynamic_text.strip(), version)

    @staticmethod
    def _fill(text: str, values: dict, name: str) -> str:
        def repl(m: re.Match) -> str:
            key = m.group(1)
            if key not in values:
                raise KeyError(f"{name}: 자리표시자 {{{{{key}}}}}에 넣을 값이 없습니다")
            return str(values[key])
        return PLACEHOLDER.sub(repl, text)
