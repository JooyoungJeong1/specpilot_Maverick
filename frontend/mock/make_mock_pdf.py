"""가상 앱(QNA) 예시 기획서 PDF를 만든다 → mock/qna-example/input.pdf

화면별 보기에서 기획서 페이지와 형광펜을 시험해 보려고 만드는 가짜 화면설계서다. 기업 기획서와 상관없다.
mock/qna-example/requirements.json의 단위 원문(quote)을 화면마다 설명표에 넣어서, 형광펜이 원문 위치를 찾을 수 있다.
  - 왼쪽: 화면 그림 (입력란·버튼과 마커 번호). 그림이 근거인 원문("화면 이미지")은 그림 안에 넣는다
  - 오른쪽: Description / Action·Event 설명표
  - 상태 화면 쪽(state_pages)에는 그 상태의 원문을 넣는다

PDF는 저장소에 올리지 않는다 (루트 .gitignore의 *.pdf). 필요한 사람이 이 스크립트로 만든다.
Chrome(또는 Edge)의 PDF 인쇄를 쓴다. 다른 위치에 설치했으면 CHROME 환경 변수로 경로를 준다.

실행 (저장소 폴더에서):
    python frontend/mock/make_mock_pdf.py
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "qna-example"
OUT = RUN / "input.pdf"

CHROME_CANDIDATES = [
    os.environ.get("CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome", "chromium", "chromium-browser",
]

SCREEN_PREFIX = re.compile(r"^([A-Z][A-Z0-9]*-\d{2,})\s+(.*)$")
ITEM = re.compile(r"(Description\s*\d+|Action(?:\s*/\s*Event)?\s*[A-Z])")


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    sys.exit("Chrome이나 Edge를 찾지 못했습니다. CHROME 환경 변수에 실행 파일 경로를 넣어 주세요.")


def item_name(src: str) -> str | None:
    """'Description 2-(1)' → 'Description 2', 'Action/Event E' → 'Action E'"""
    m = ITEM.search(src)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("Description"):
        no = int(re.sub(r"\D", "", s))
        return f"Description {no}"
    return f"Action {s[-1]}"


def sort_key(item: str):
    kind, no = item.split(" ")
    return (0 if kind == "Description" else 1, int(no) if no.isdigit() else ord(no))


class Page:
    def __init__(self):
        self.items: dict[str, list[str]] = {}   # 설명표 항목 → 문장
        self.picture: list[str] = []            # 그림 안 글자
        self.state: list[str] = []              # 상태 화면 문장

    def text(self) -> str:
        return " ".join(sum(self.items.values(), []) + self.picture + self.state)

    def add(self, item: str, sentence: str):
        if sentence and sentence not in self.text():
            self.items.setdefault(item, []).append(sentence)


def collect(req: dict) -> dict[str, Page]:
    pages = {s["screen_id"]: Page() for s in req["app_profile"]["screens"]}
    units = req["units"]
    # 화면 단위 먼저 (원문이 그 화면 항목에 그대로 들어가게), 앱 전체 단위는 나중에 빠진 원문만 더한다
    for u in sorted(units, key=lambda u: u["screen_id"] == "APP"):
        segs = [s.strip() for s in u["quote"].split(" / ") if s.strip()]
        for i, seg in enumerate(segs):
            src = u["source"][min(i, len(u["source"]) - 1)]
            sid = u["screen_id"]
            m = SCREEN_PREFIX.match(src.strip())
            if m:
                sid, src = m.group(1), m.group(2)
            page = pages.get(sid)
            if page is None:
                continue
            if "상태 화면" in src:
                if seg not in page.text():
                    page.state.append(seg)
            elif "이미지" in src or "그림" in src:
                if seg not in page.text():
                    page.picture.append(seg)
            else:
                page.add(item_name(src) or "Description 0", seg)
    for sid, skipped in req.get("skipped", {}).items():
        for s in skipped:
            item = item_name(s["source"])
            if item and sid in pages:
                pages[sid].add(item, re.sub(r"\(.*?\)", "", s["reason"]).strip() + " 영역이다.")
    return pages


def wireframe(screen: dict, page: Page, units: list[dict], rejected: bool) -> str:
    """화면 그림: 표시 단위의 값으로 입력란, Action 항목으로 버튼을 그리고 마커 번호를 붙인다"""
    sid = screen["screen_id"]
    fields: list[str] = []
    for u in units:
        if u["screen_id"] == sid and u["kind"] == "표시":
            fields += [v for v in u["exact"]["values"] if v not in fields]
    buttons = []
    for item in sorted(page.items, key=sort_key):
        if item.startswith("Action"):
            first = page.items[item][0]
            # "회원가입: …"처럼 앞에 버튼 이름이 있으면 그 이름, 오류 문구("* error-msg: …") 등은 "버튼 E"
            head = first.split(":")[0]
            label = head if ":" in first[:12] and not head.startswith("*") else item.replace("Action ", "버튼 ")
            buttons.append((item[-1], label))
    descs = [i for i in sorted(page.items, key=sort_key) if i.startswith("Description")]
    marker = lambda m: f'<span class="mk">{html.escape(m)}</span>'  # noqa: E731
    if rejected:   # 반려 화면: 그림 마커와 설명 번호가 맞지 않게 그린다
        rows = "".join(f'<div class="fld">{marker(str(n))}<span>입력 영역 {n}</span></div>' for n in (3, 5, 8, 9))
        btns = "".join(f'<span class="b">{marker(m)}버튼</span>' for m in "WXYZ")
        return f'<div class="win"><div class="tb">{html.escape(screen["name"])}</div>{rows}<div class="btns">{btns}</div><div class="cut">(그림 일부가 잘림)</div></div>'
    head = "".join(f'<div class="hint">{html.escape(t)}</div>' for t in page.picture)
    nums = [d.split(" ")[1] for d in descs] or ["0"]
    rows = "".join(f'<div class="fld">{marker(nums[min(i + 1, len(nums) - 1)])}<span>{html.escape(f)}</span></div>' for i, f in enumerate(fields[:6]))
    btns = "".join(f'<span class="b">{marker(m)}{html.escape(lbl)}</span>' for m, lbl in buttons[:6])
    return (f'<div class="win"><div class="tb">{marker(nums[0])}{html.escape(screen["name"])}<span class="lo">로그아웃</span></div>'
            f'{head}{rows}<div class="btns">{btns}</div></div>')


def table(page: Page, rejected: bool) -> str:
    if rejected:
        rows = [("Description 1", "답변 내용을 입력한다."), ("Description 2", "답변은 1000자까지 입력할 수 있다."),
                ("Action A", "등록: 답변을 저장하고 문의 상세로 이동한다."), ("Action B", "취소")]
    else:
        rows = [(item, " ".join(page.items[item])) for item in sorted(page.items, key=sort_key)]
    trs = "".join(f'<tr><td class="s">{html.escape(a.replace("Action ", "Action/Event "))}</td><td>{html.escape(b)}</td></tr>' for a, b in rows)
    return f'<table><tr><th colspan="2">Description</th></tr>{trs}</table>'


CSS = """
@page{size:A4 landscape;margin:0}
body{margin:0;font-family:"Malgun Gothic","Apple SD Gothic Neo","Noto Sans KR",sans-serif;color:#222}
section{height:100vh;box-sizing:border-box;padding:22px 28px;page-break-after:always;display:flex;flex-direction:column}
.hd{display:flex;gap:16px;align-items:baseline;border-bottom:2px solid #333;padding-bottom:6px;margin-bottom:14px;font-size:13px}
.hd b{font-size:18px}.hd .tag{margin-left:auto;color:#999;font-size:11px}
.body{flex:1;display:flex;gap:22px;min-height:0}
.pic{flex:1.25;border:1px solid #bbb;background:#f6f7fb;padding:18px;box-sizing:border-box}
.win{background:#fff;border:2px solid #556;border-radius:6px;height:100%;box-sizing:border-box;padding:0 0 16px;position:relative}
.tb{background:#e4e7f2;padding:8px 12px;font-weight:bold;font-size:14px;display:flex;align-items:center;gap:6px}
.tb .lo{margin-left:auto;font-weight:normal;font-size:12px;border:1px solid #889;padding:1px 8px;border-radius:3px}
.hint{margin:10px 16px 0;font-size:12px;color:#556}
.fld{display:flex;align-items:center;gap:8px;margin:14px 16px 0}
.fld span:last-child{flex:1;border:1px solid #99a;border-radius:4px;padding:7px 10px;font-size:12px;color:#777}
.btns{display:flex;flex-wrap:wrap;gap:10px;margin:18px 16px 0}
.b{display:inline-flex;align-items:center;gap:6px;border:1px solid #3346a8;color:#3346a8;border-radius:4px;padding:6px 12px;font-size:12px}
.mk{display:inline-flex;width:18px;height:18px;border-radius:50%;background:#d33;color:#fff;font-size:10px;align-items:center;justify-content:center;font-weight:bold;flex:none}
.cut{position:absolute;bottom:0;left:0;right:0;height:40%;background:repeating-linear-gradient(45deg,#eee,#eee 6px,#f8f8f8 6px,#f8f8f8 12px);display:flex;align-items:center;justify-content:center;color:#999;font-size:12px}
.state{flex:1.25;border:1px dashed #d88;background:#fff7f7;padding:18px;font-size:13px}
table{flex:1;border-collapse:collapse;font-size:11.5px;align-self:flex-start}
th{background:#333;color:#fff;padding:6px;text-align:left}
td{border:1px solid #999;padding:6px;vertical-align:top;line-height:1.5}
td.s{width:92px;color:#444;background:#f2f2f2}
"""


def build_html(req: dict) -> str:
    screens = req["app_profile"]["screens"]
    pages = collect(req)
    total = max(max(s["pages"] + s["state_pages"]) for s in screens)
    by_page: dict[int, str] = {}
    for s in screens:
        sid = s["screen_id"]
        rejected = sid in req.get("rejected_screens", {})
        p = pages[sid]
        head = f'<div class="hd"><b>{html.escape(sid)} {html.escape(s["name"])}</b><span>{html.escape(s.get("depth") or "")}</span><span class="tag">가상 문의 앱 · 예시 화면설계서 (실제 기획서 아님)</span></div>'
        for n in s["pages"]:
            if n in s["state_pages"] and n != s["pages"][0]:
                body = f'<div class="state"><b>상태 화면: 로그인 실패</b><p>{"</p><p>".join(html.escape(t) for t in p.state)}</p></div>{table(Page(), False)}'
            else:
                body = wireframe(s, p, req["units"], rejected).join(['<div class="pic">', '</div>']) + table(p, rejected)
            by_page[n] = f'<section>{head}<div class="body">{body}</div></section>'
    blank = '<section><div class="hd"><b>(빈 쪽)</b></div></section>'
    return f'<!doctype html><meta charset="utf-8"><style>{CSS}</style>' + "".join(by_page.get(n, blank) for n in range(1, total + 1))


def main() -> None:
    req = json.loads((RUN / "requirements.json").read_text(encoding="utf-8"))
    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "plan.html"
        page.write_text(build_html(req), encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={OUT}", page.as_uri()], check=True, capture_output=True, timeout=120)
    print(f"만들었습니다: {OUT} ({OUT.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    main()
