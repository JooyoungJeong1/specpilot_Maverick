"""PDF 자르기, 글자 읽기, 기획서 항목 번호 찾기, 원문 대조.

글자를 읽는 방법은 두 가지다.
- pdftotext(poppler)가 있으면 글자마다 좌표를 받아(-bbox) 오른쪽 설명표의 번호 칸과 왼쪽 화면 그림을 나눠 읽는다.
  항목 번호(체크리스트), 그림 속 마커 번호, 원문 대조가 모두 이 방식이 정확하다.
- 없으면 pypdf로 읽는다. 항목 번호를 덜 찾고 그림 마커는 읽지 못한다(그 검사는 건너뛴다).
"""
from __future__ import annotations

import base64
import html
import io
import re
import shutil
import subprocess
import tempfile
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader, PdfWriter

ITEM_LINE = re.compile(r"^(\s*)(\d{1,2}|[A-Z])\s{2,}\S")
ITEM_TOKEN = re.compile(r"\d{1,2}|[A-Z]")
PANEL_MIN_X = 0.55          # 설명표는 페이지 오른쪽에 있다고 본다 (가로 길이 대비 위치)


def page_count(pdf_path: Path) -> int:
    return len(PdfReader(str(pdf_path)).pages)


def subset_pdf(pdf_path: Path, pages: list[int]) -> bytes:
    """1부터 세는 페이지 번호 목록으로 새 PDF를 만든다."""
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for p in pages:
        writer.add_page(reader.pages[p - 1])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def document_block(pdf_bytes: bytes, cache: bool = False) -> dict:
    block = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
        },
    }
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return block


def has_pdftotext() -> bool:
    return shutil.which("pdftotext") is not None


def text_extractor() -> str:
    """글자 추출에 쓰는 도구 이름. meta에 남겨서 검사가 얼마나 믿을 만한지 알 수 있게 한다."""
    return "pdftotext" if has_pdftotext() else "pypdf"


def _run_pdftotext(args: list[str]) -> str | None:
    result = subprocess.run(["pdftotext", "-enc", "UTF-8", *args],
                            capture_output=True, encoding="utf-8", errors="replace")
    return result.stdout if result.returncode == 0 else None


def _pdftotext(args: list[str]) -> str | None:
    """pdftotext를 부르고 출력 글자를 돌려준다. 실패하면 None.
    출력 인코딩을 UTF-8로 고정한다. 지정하지 않으면 한글 Windows에서 cp949로 읽혀 글자가 깨진다.
    파일 경로에 한글이 있으면 일부 Windows용 pdftotext가 파일을 못 열어서, 영문 이름의 임시 사본으로 한 번 더 시도한다."""
    if not has_pdftotext():
        return None
    out = _run_pdftotext(args)
    if out is None:
        targets = [a for a in args if a.lower().endswith(".pdf") and not a.isascii() and Path(a).exists()]
        if targets:
            with tempfile.TemporaryDirectory() as d:
                tmp = Path(d) / "input.pdf"
                shutil.copyfile(targets[0], tmp)
                out = _run_pdftotext([str(tmp) if a == targets[0] else a for a in args])
    return out


def page_text(pdf_path: Path, page: int) -> str:
    """페이지 글자를 배치(layout)를 살려 뽑는다. pdftotext가 있으면 그쪽이 더 정확하다."""
    out = _pdftotext(["-layout", "-f", str(page), "-l", str(page), str(pdf_path), "-"])
    if out is not None:
        return out
    return _pypdf_text(pdf_path, page)


def _pypdf_text(pdf_path: Path, page: int, layout: bool = True) -> str:
    # 글자가 없는 빈 페이지나 일부 PDF는 layout 모드에서 오류가 나므로, 실패하면 기본 모드로 읽고 그래도 안 되면 빈 글자로 본다.
    page_obj = PdfReader(str(pdf_path)).pages[page - 1]
    modes = ({"extraction_mode": "layout"}, {}) if layout else ({},)
    for kwargs in modes:
        try:
            return page_obj.extract_text(**kwargs) or ""
        except Exception:
            continue
    return ""


# ---------- 좌표로 읽기 (pdftotext -bbox) ----------

@dataclass
class Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str


@dataclass
class PageLayout:
    page: int
    width: float
    height: float
    words: list[Word]
    item_col: float | None = None                         # 설명표 번호 칸의 x 위치. 못 찾으면 None
    items: list[tuple[float, str]] = field(default_factory=list)   # (y, "Description 3" / "Action A"), 위에서 아래 순서
    picture_numbers: set[int] = field(default_factory=set)         # 그림 속 숫자 마커
    picture_letters: set[str] = field(default_factory=set)         # 그림 속 알파벳 마커

    @property
    def char_count(self) -> int:
        return sum(len(w.text) for w in self.words)

    @property
    def panel_left(self) -> float | None:
        return None if self.item_col is None else self.item_col - 4

    def item_names(self) -> list[str]:
        return [name for _, name in self.items]


_PAGE_RE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', re.S)
_WORD_RE = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')


def _item_name(token: str) -> str:
    return f"Description {int(token)}" if token.isdigit() else f"Action {token}"


def _analyze(layout: PageLayout) -> PageLayout:
    """오른쪽 설명표의 번호 칸과 왼쪽 그림의 마커를 찾는다.

    설명표의 번호(0, 1, 2 … / A, B …)는 같은 x 위치에 세로로 줄지어 있다.
    오른쪽에 있는 한두 글자짜리 숫자·알파벳 중 x가 가장 많이 겹치는 칸을 번호 칸으로 본다.
    """
    cand = [w for w in layout.words if w.x0 > layout.width * PANEL_MIN_X and ITEM_TOKEN.fullmatch(w.text)]
    if not cand:
        return layout
    bucket, n = Counter(round(w.x0 / 4) for w in cand).most_common(1)[0]
    if n < 2:
        return layout
    col = [w for w in cand if abs(round(w.x0 / 4) - bucket) <= 1]
    layout.item_col = min(w.x0 for w in col)
    layout.items = sorted((w.y0, _item_name(w.text)) for w in col)
    left = layout.panel_left
    for w in layout.words:
        if w.x1 < left and ITEM_TOKEN.fullmatch(w.text):
            if w.text.isdigit():
                layout.picture_numbers.add(int(w.text))
            else:
                layout.picture_letters.add(w.text)
    return layout


_layout_cache: dict[tuple, list[PageLayout]] = {}
_layout_lock = threading.Lock()


def read_layout(pdf_path: Path) -> list[PageLayout] | None:
    """PDF 전체를 좌표와 함께 읽는다. pdftotext가 없거나 실패하면 None."""
    path = Path(pdf_path)
    st = path.stat()
    key = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    with _layout_lock:
        if key in _layout_cache:
            return _layout_cache[key]
    out = _pdftotext(["-bbox", str(path), "-"])
    if out is None:
        return None
    pages = []
    for i, (w, h, body) in enumerate(_PAGE_RE.findall(out), 1):
        words = [Word(float(a), float(b), float(c), float(d), html.unescape(t).strip())
                 for a, b, c, d, t in _WORD_RE.findall(body)]
        pages.append(_analyze(PageLayout(i, float(w), float(h), [w_ for w_ in words if w_.text])))
    with _layout_lock:
        _layout_cache[key] = pages
    return pages


def _lines(words: list[Word]) -> list[list[Word]]:
    """같은 높이의 단어끼리 한 줄로 묶고, 줄 안에서는 왼쪽부터 놓는다."""
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.y0, w.x0)):
        if out:
            last = out[-1]
            ref = last[0]
            if abs(w.y0 - ref.y0) <= max(2.0, 0.5 * (ref.y1 - ref.y0)):
                last.append(w)
                continue
        out.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in out]


def _region_text(words: list[Word]) -> str:
    return "\n".join(" ".join(w.text for w in line) for line in _lines(words))


def panel_text(layout: PageLayout) -> str:
    """설명표 부분 글자 (줄 순서대로)."""
    if layout.panel_left is None:
        return ""
    return _region_text([w for w in layout.words if w.x0 >= layout.panel_left - 2])


def picture_text(layout: PageLayout) -> str:
    """설명표 왼쪽(화면 그림, 머리글) 글자."""
    left = layout.panel_left if layout.panel_left is not None else layout.width + 1
    return _region_text([w for w in layout.words if w.x0 < left - 2])


# ---------- 기획서 항목 번호 (체크리스트) ----------

def detect_items(text: str) -> set[str]:
    """(좌표를 못 쓸 때) 배치 글자에서 설명 칸에 있는 Description 번호와 Action 글자를 찾는다.

    화면 이미지 안의 마커와 설명 칸의 항목이 둘 다 "1  ..." 모양이라,
    두 번 이상 나온 들여쓰기 중 가장 오른쪽 것을 설명 칸으로 본다.
    글자 추출이 불완전해서 일부 항목을 놓칠 수 있다(놓친 항목은 검사하지 않을 뿐 오류는 아님).
    반환 예: {"Description 0", "Description 3", "Action E"}
    """
    hits: list[tuple[int, str]] = []
    for line in text.splitlines():
        m = ITEM_LINE.match(line)
        if m:
            hits.append((len(m.group(1)), m.group(2)))
    if not hits:
        return set()
    counts: dict[int, int] = {}
    for indent, _ in hits:
        counts[indent] = counts.get(indent, 0) + 1
    repeated = [i for i, c in counts.items() if c >= 2]
    if not repeated:
        return set()
    column = max(repeated)
    items = set()
    for indent, mark in hits:
        if abs(indent - column) <= 2:
            items.add(_item_name(mark))
    return items


def _description_column(text: str) -> int | None:
    counts: dict[int, int] = {}
    for line in text.splitlines():
        m = ITEM_LINE.match(line)
        if m:
            counts[len(m.group(1))] = counts.get(len(m.group(1)), 0) + 1
    repeated = [i for i, c in counts.items() if c >= 2]
    return max(repeated) if repeated else None


def item_block(text: str, item: str, max_lines: int = 15) -> str | None:
    """(좌표를 못 쓸 때) 페이지 글자에서 항목 하나("Description 3", "Action E")의 설명 부분만 잘라 낸다. 못 찾으면 None."""
    kind, _, mark = item.partition(" ")
    column = _description_column(text)
    if column is None or not mark:
        return None
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        m = ITEM_LINE.match(line)
        at_column = bool(m) and abs(len(m.group(1)) - column) <= 2
        if at_column:
            this = _item_name(m.group(2))
            if inside:
                break
            inside = this == f"{kind} {mark}"
        if inside:
            part = line[max(0, column - 2):].rstrip()
            if part.strip():
                out.append(part.strip())
            if len(out) >= max_lines:
                break
    return "\n".join(out) if out else None


def item_text(pdf_path: Path, page: int, item: str, max_lines: int = 15) -> str | None:
    """항목 하나의 설명 원문. 좌표로 읽을 수 있으면 그 항목 줄부터 다음 항목 줄 전까지 자른다."""
    layouts = read_layout(pdf_path)
    if layouts and 1 <= page <= len(layouts) and layouts[page - 1].items:
        lay = layouts[page - 1]
        ys = [y for y, name in lay.items if name == item]
        if not ys:
            return None
        start = ys[0]
        nexts = [y for y, _ in lay.items if y > start + 1]
        end = min(nexts) if nexts else float("inf")
        words = [w for w in lay.words if w.x0 >= lay.panel_left - 2 and start - 2 <= w.y0 < end - 2]
        lines = [" ".join(w.text for w in line) for line in _lines(words)]
        return "\n".join(lines[:max_lines]) or None
    return item_block(page_text(pdf_path, page), item, max_lines)


def expected_items(pdf_path: Path, pages: list[int]) -> set[str]:
    """(좌표를 못 쓸 때) 페이지들의 기획서 항목 번호."""
    items: set[str] = set()
    for p in pages:
        items |= detect_items(page_text(pdf_path, p))
    return items


def copy_input(pdf_path: Path, run_dir: Path) -> Path:
    dest = run_dir / "input.pdf"
    shutil.copyfile(pdf_path, dest)
    return dest


# ---------- 원문 대조 ----------

_QUOTE_CHARS = "\"'`‘’“”「」『』〈〉《》"
_DROP = {ord(c): None for c in _QUOTE_CHARS + "​‌‍﻿"}
_WS = re.compile(r"\s+")


def squash(text: str | None) -> str:
    """대조용으로 글자를 정리한다: 호환 문자 통일(NFKC), 공백·따옴표 제거.
    띄어쓰기와 따옴표 모양은 추출 도구마다 달라서 비교하지 않는다."""
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", str(text)).translate(_DROP)
    return _WS.sub("", t)


def approx_distance(pattern: str, text: str) -> int:
    """pattern과, text 안의 가장 비슷한 부분 사이의 최소 편집 거리 (Myers 비트 병렬 방식).
    0이면 그대로 들어 있다는 뜻이고, 1이면 한 글자만 다르다는 뜻이다."""
    m = len(pattern)
    if m == 0:
        return 0
    peq: dict[str, int] = {}
    for i, c in enumerate(pattern):
        peq[c] = peq.get(c, 0) | (1 << i)
    full = (1 << m) - 1
    high = 1 << (m - 1)
    pv, mv, score, best = full, 0, m, m
    for c in text:
        eq = peq.get(c, 0)
        xv = eq | mv
        xh = ((((eq & pv) + pv) & full) ^ pv) | eq
        ph = mv | (full & ~(xh | pv))
        mh = pv & xh
        if ph & high:
            score += 1
        elif mh & high:
            score -= 1
        ph = (ph << 1) & full
        mh = (mh << 1) & full
        pv = mh | (full & ~(xv | ph))
        mv = ph & xv
        if score < best:
            best = score
            if best == 0:
                break
    return best


def allowed_edits(n: int) -> int:
    """원문과 '조금 다름'으로 볼 수 있는 편집 수. 글자 하나를 고친 정도(약 12%)까지."""
    return max(1, round(n * 0.12))


class TextIndex:
    """설계서 글자를 페이지별로 모아 두고, 인용문이 원문에 있는지 찾는다.

    같은 페이지를 여러 방식(설명표 줄 순서, 그림 영역, pdftotext 기본 순서)으로 읽어 이어 둔다.
    여러 줄에 걸친 문장도 어느 한 방식에서는 이어져 있기 때문이다.
    strong이 False(pdftotext 없음)면 읽기가 부정확하므로 결과를 경고로만 쓴다.
    """

    def __init__(self, pdf_path: Path):
        self.pdf_path = Path(pdf_path)
        self.strong = has_pdftotext()
        self._pages: dict[int, str] | None = None
        self._lock = threading.Lock()

    def _build(self) -> dict[int, str]:
        with self._lock:
            if self._pages is not None:
                return self._pages
            pages: dict[int, str] = {}
            layouts = read_layout(self.pdf_path) if self.strong else None
            plain = _pdftotext([str(self.pdf_path), "-"]) if self.strong else None
            plain_pages = plain.split("\f") if plain is not None else []
            total = page_count(self.pdf_path)
            for p in range(1, total + 1):
                parts = []
                if layouts and p <= len(layouts):
                    parts += [panel_text(layouts[p - 1]), picture_text(layouts[p - 1])]
                if p <= len(plain_pages):
                    parts.append(plain_pages[p - 1])
                if not parts:
                    parts.append(_pypdf_text(self.pdf_path, p, layout=False))
                pages[p] = "\x00".join(squash(x) for x in parts)
            self._pages = pages
            return pages

    def page_numbers(self) -> list[int]:
        return sorted(self._build())

    def find(self, segment: str, pages: list[int] | None = None) -> str | None:
        """'exact'(그대로 있음) / 'approx'(한두 글자 다름) / None(없음)."""
        s = squash(segment)
        if not s:
            return "exact"
        texts = self._build()
        chosen = [texts[p] for p in (pages or texts) if p in texts]
        if any(s in t for t in chosen):
            return "exact"
        limit = allowed_edits(len(s))
        if any(approx_distance(s, t) <= limit for t in chosen):
            return "approx"
        return None
