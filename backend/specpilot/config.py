"""실행 설정. 값은 환경 변수(.env)로 바꾼다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """프로젝트 루트의 .env를 읽어 환경 변수로 넣는다 (이미 있는 값은 덮어쓰지 않음)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


_load_dotenv()


@dataclass
class Settings:
    model: str = field(default_factory=lambda: os.getenv("SPECPILOT_MODEL", "claude-sonnet-5"))
    # 생각(thinking) 토큰과 답 토큰을 합친 한도. Sonnet 5는 기본으로 먼저 생각하고 답하므로 넉넉히 잡는다.
    max_tokens: int = field(default_factory=lambda: int(os.getenv("SPECPILOT_MAX_TOKENS", "32000")))
    # 생각 켜기/끄기: "adaptive"(모델 기본, 필요할 때 생각) | "disabled"(생각 안 함)
    thinking: str = field(default_factory=lambda: os.getenv("SPECPILOT_THINKING", "adaptive").strip().lower())
    # 생각을 얼마나 할지: low | medium | high. 비우면 모델 기본값
    effort: str = field(default_factory=lambda: os.getenv("SPECPILOT_EFFORT", "medium").strip().lower())
    # 검사에 걸렸을 때 같은 화면을 다시 부르는 횟수 (첫 호출 제외)
    max_retries: int = field(default_factory=lambda: int(os.getenv("SPECPILOT_MAX_RETRIES", "2")))
    prompts_dir: Path = field(default_factory=lambda: Path(os.getenv("SPECPILOT_PROMPTS_DIR", str(ROOT / "prompts"))))
    output_dir: Path = field(default_factory=lambda: Path(os.getenv("SPECPILOT_OUTPUT_DIR", str(ROOT / "output"))))
    # True면 ②에도 PDF 전체를 보낸다. 기본은 그 화면의 페이지만 잘라서 보낸다.
    send_full_pdf: bool = field(default_factory=lambda: _bool("SPECPILOT_FULL_PDF", False))
    # True면 커버리지 누락(기획서 항목이 단위·skipped 어디에도 없음)도 재시도 사유로 본다.
    coverage_strict: bool = field(default_factory=lambda: _bool("SPECPILOT_COVERAGE_STRICT", True))
    # True면 quote·문구가 설계서 원문에 없을 때(지어낸 근거) 재시도한다. False면 경고만 남긴다.
    # 한두 글자 다른 것(오타를 고쳐 쓴 정도)은 어느 쪽이든 경고만 남긴다.
    quote_strict: bool = field(default_factory=lambda: _bool("SPECPILOT_QUOTE_STRICT", True))
    # 입력 점검: 그림 마커와 설명 번호가 이 비율보다 적게 맞으면 그 쪽(화면)을 반려한다.
    marker_match_min: float = field(default_factory=lambda: float(os.getenv("SPECPILOT_MARKER_MATCH_MIN", "0.5")))
    # 입력 점검: 반려된 쪽(화면)이 이 비율 이상이면 기획서 전체를 반려한다.
    reject_ratio: float = field(default_factory=lambda: float(os.getenv("SPECPILOT_REJECT_RATIO", "0.5")))
    # ③: 코드 전체가 이 토큰 수 이하면 통째로(캐시), 넘으면 화면별 묶음으로 보낸다.
    code_token_limit: int = field(default_factory=lambda: int(os.getenv("SPECPILOT_CODE_TOKEN_LIMIT", "100000")))
