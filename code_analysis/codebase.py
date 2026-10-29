"""③과 똑같은 파일 목록과 줄 번호로 코드를 읽는다.

③(backend/specpilot/code_prep.py의 load_codebase)이 어떤 파일을 넣고 경로를 어떻게 쓰는지에
사실의 file·line을 맞춰야 한다. 그래서 백엔드 함수를 그대로 불러 쓰고, 불러올 수 없을 때만
같은 규칙을 옮겨 둔 사본(_load_mirror)을 쓴다. 두 결과가 같은지는 테스트가 확인한다.

분석기는 파일을 디스크에서 다시 읽지 않고, 이 목록의 줄을 "\\n"으로 이어 붙인 글자를 파싱한다.
그래서 분석기가 내는 줄 번호가 ③이 붙이는 "줄번호|"와 항상 같다 (\\r, \\u2028 같은 줄바꿈 차이가 생기지 않음).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

# ---- backend/specpilot/code_prep.py 의 규칙 사본 (백엔드를 불러올 수 없을 때만 쓴다) ----
CODE_EXTS = {
    ".java", ".kt", ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".html", ".htm", ".jsp", ".css", ".xml", ".yml", ".yaml", ".properties", ".sql",
}
EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", ".gradle", "node_modules", "build", "target", "dist", "out",
    "bin", "gradle", "__pycache__", ".venv", "venv", "test", "tests", "__tests__", "coverage",
}
MAX_FILE_BYTES = 300_000
MIN_FILE_NAME = re.compile(r"\.min\.(js|css)$")


@dataclass
class Code:
    root: Path
    files: dict[str, list[str]] = field(default_factory=dict)   # 상대 경로(/) → 줄 목록 (③과 같음)
    loader: str = "backend"                                     # backend | mirror

    def text(self, path: str) -> str:
        """분석기에 넘기는 글자. 줄 목록을 \\n으로 이어서, 파서의 줄 번호가 ③의 줄 번호와 같게 한다."""
        return "\n".join(self.files[path])

    def line(self, path: str, no: int) -> str:
        lines = self.files.get(path, [])
        return lines[no - 1] if 1 <= no <= len(lines) else ""

    def by_suffix(self, suffix: str) -> list[str]:
        return [p for p in self.files if p.lower().endswith(suffix)]


def _load_mirror(root: Path) -> dict[str, list[str]]:
    files: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CODE_EXTS:
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        if MIN_FILE_NAME.search(path.name) or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files[rel.as_posix()] = text.splitlines()
    return files


def _backend_loader():
    """backend/specpilot/code_prep.load_codebase를 불러온다. 실패하면 None."""
    if not (BACKEND_DIR / "specpilot" / "code_prep.py").is_file():
        return None
    added = str(BACKEND_DIR)
    if added not in sys.path:
        sys.path.insert(0, added)
    try:
        from specpilot.code_prep import load_codebase  # type: ignore
    except Exception:
        return None
    return load_codebase


def load(root: Path, prefer_backend: bool = True) -> Code:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"코드 폴더가 없습니다: {root.resolve()}")
    loader = _backend_loader() if prefer_backend else None
    if loader is not None:
        cb = loader(root)
        return Code(root=root, files=dict(cb.files), loader="backend")
    return Code(root=root, files=_load_mirror(root), loader="mirror")
