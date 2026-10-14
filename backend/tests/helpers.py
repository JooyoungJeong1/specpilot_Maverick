"""테스트 도우미: 원문 대조용 가짜 글자 모음, 좌표를 지정해 글자를 놓는 작은 PDF 만들기.

PDF는 영문·숫자만 쓴다 (한글 글꼴을 넣지 않아도 되게). 실제 기획서 내용은 넣지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from specpilot.pdf_utils import allowed_edits, approx_distance, squash

ROOT = Path(__file__).resolve().parent.parent


class FakeTexts:
    """TextIndex 대신 쓰는 가짜. corpus가 None이면 무엇이든 원문에 있다고 본다."""

    def __init__(self, corpus: str | None = None, strong: bool = True):
        self.corpus = None if corpus is None else squash(corpus)
        self.strong = strong

    def find(self, segment, pages=None):
        s = squash(segment)
        if self.corpus is None or not s or s in self.corpus:
            return "exact"
        return "approx" if approx_distance(s, self.corpus) <= allowed_edits(len(s)) else None


def example_input(title: str) -> str:
    """프롬프트 ②에 적힌 예시 입력 화면 글자 (예: "5. 예시 1"). 예시 출력의 quote가 이 글자에서 나왔는지 대조할 때 쓴다."""
    text = (ROOT / "prompts" / "screen_decompose.txt").read_text(encoding="utf-8")
    start = text.index(f"# {title}")
    body = text[start:]
    return body[body.index("입력 화면"):body.index("출력")]


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages: list[list[tuple[float, float, str]]], width: float = 842, height: float = 595) -> Path:
    """pages: 쪽마다 (x, 위에서부터 y, 글자) 목록. 글자가 없는 쪽은 빈 목록."""
    objs: list[bytes] = []
    n_pages = len(pages)
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, words in enumerate(pages):
        content = "".join(f"BT /F1 9 Tf {x:.1f} {height - y:.1f} Td ({_escape(t)}) Tj ET\n" for x, y, t in words).encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[i] + 1} 0 R >>".encode())
        objs.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))
    return Path(path)


def screen_page(desc: list[int], actions: str = "AB", markers: list[int] | None = None,
                letters: str | None = None, sentences: dict[str, str] | None = None) -> list[tuple[float, float, str]]:
    """기획서 한 쪽 흉내: 왼쪽에 화면 그림(마커), 오른쪽에 설명표(번호 + 설명 문장)."""
    sentences = sentences or {}
    words = [(40, 20, "Depth"), (200, 20, "Screen"), (620, 20, "ID")]
    words += [(80, 60, "Login"), (80, 200, "Email"), (80, 260, "Password")]          # 그림 속 화면 글자
    markers = desc[1:] if markers is None else markers
    for i, m in enumerate(markers):                                                   # 그림 속 숫자 마커
        words.append((60 + 30 * (i % 6), 120 + 40 * (i // 6), str(m)))
    for i, c in enumerate(actions if letters is None else letters):                   # 그림 속 알파벳 마커
        words.append((300, 120 + 30 * i, c))
    y = 60
    for d in desc:                                                                    # 설명표: 번호 칸 x=600
        words.append((600, y, str(d)))
        words.append((620, y, sentences.get(str(d), f"{_NAMES[d % len(_NAMES)]} rule applies here")))
        y += 24
    for c in actions:
        words.append((600, y, c))
        words.append((620, y, sentences.get(c, f"{c.lower()}{c.lower()} button opens next page")))
        y += 24
    return words


# 설명 문장에는 숫자나 대문자 한 글자를 넣지 않는다 (번호 칸으로 오인되지 않게)
_NAMES = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel",
          "india", "juliet", "kilo", "lima", "mike", "november"]
