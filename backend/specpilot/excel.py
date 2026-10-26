"""테스트 사양서 엑셀 (④ 결과). 기업 샘플 사양서 양식을 따른다.

- 개정이력, 00. 목차: 메뉴(DEPTH(1))·화면(DEPTH(2))별 시나리오·단계 수
- NN. <DEPTH(1)>: 정보 칸(프로젝트명, 시험대상 메뉴명, 작성자·작성일, 테스트확인자·시행일)과 두 줄 머리글
  (시험번호/시나리오명, 시험구분 DEPTH(1)·(2), No, 시험절차, 예상결과, 시험데이터 계정·입력값·비고, 확인결과)
  + 우리가 더한 열: 근거 요구사항, 데이터 출처
- 확인 질문: ①②의 확인 질문과 단위 issue (기획자에게 확인할 것)
- 추적표: 기획서에서 뽑은 요구사항 단위 전체 → 시나리오·단계 (제약 단위, 사양서에 못 넣은 단위,
  아직 ④를 돌리지 않은 화면의 단위 표시). 사양서가 기획서를 빠짐없이 다뤘는지 보는 표다.

판정 결과는 넣지 않는다. 사양서는 기획서만 보고 만든다.
"""
from __future__ import annotations

import math
import re
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

FONT = "맑은 고딕"
HEAD_FILL = PatternFill("solid", fgColor="D9D9D9")
INFO_FILL = PatternFill("solid", fgColor="F2F2F2")
SETUP_COLOR = "7F7F7F"
THIN = Side(style="thin", color="808080")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
DATE_FORMAT = "yyyy-mm-dd"
WRITER = "SpecPilot (자동 생성)"
DATA_SOURCE = {"설계서": "기획서"}          # 프롬프트 안의 말(설계서)을 사양서에서는 기획서로 보여 준다
SPEC_WIDTHS = {"A": 20, "B": 14, "C": 18, "D": 5, "E": 46, "F": 46, "G": 24, "H": 24, "I": 32, "J": 9, "K": 22, "L": 10}
SPEC_FIRST_ROW = 6


def _f(bold=False, color=None, size=10) -> Font:
    return Font(name=FONT, size=size, bold=bold, color=color)


def sheet_title(name: str, used: set[str]) -> str:
    """엑셀 시트 이름: 31자까지, : \\ / ? * [ ] 는 쓸 수 없고, 겹치면 번호를 붙인다."""
    base = (re.sub(r"[:\\/?*\[\]]", " ", name).strip() or "시트")[:31]
    title, i = base, 2
    while title in used:
        title = f"{base[:31 - len(str(i)) - 1]} {i}"
        i += 1
    used.add(title)
    return title


def _lines(value, width: float) -> int:
    """칸 너비에서 몇 줄로 보일지 어림한다 (한글은 영문의 약 2배 폭)."""
    if value is None or value == "":
        return 1
    n = 0
    for para in str(value).split("\n"):
        w = sum(1 if ord(ch) < 128 else 1.9 for ch in para)
        n += max(1, math.ceil(w / max(width - 1, 1)))
    return n


def _fit_rows(ws, first: int, widths: dict[str, float]) -> None:
    """줄바꿈한 칸이 잘리지 않게 행 높이를 맞춘다 (엑셀은 파일을 열 때 높이를 다시 재지 않는다)."""
    for row in ws.iter_rows(min_row=first):
        lines = max((_lines(c.value, widths.get(c.column_letter, 10)) for c in row), default=1)
        ws.row_dimensions[row[0].row].height = max(18, 15 * lines + 3)


def _cell(ws, ref: str, value, *, bold=False, fill=None, align=WRAP, color=None, fmt=None):
    c = ws[ref]
    c.value = value
    c.font = _f(bold=bold, color=color)
    c.alignment = align
    c.border = BORDER
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    return c


def _box(ws, area: str) -> None:
    """병합한 칸의 테두리를 모두 그린다."""
    for row in ws[area]:
        for c in row:
            c.border = BORDER


def _widths(ws, widths: dict[str, float]) -> None:
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _print_setup(ws, title_rows: str | None = None) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    if title_rows:
        ws.print_title_rows = title_rows


def _screen_label(sid: str | None, names: dict[str, str]) -> str:
    if not sid:
        return ""
    return "앱 전체" if sid == "APP" else f"{sid} {names.get(sid, '')}".strip()


def _step_refs(scenarios: list[dict]) -> dict[str, list[str]]:
    """단위 ID → ["TC-…-01 #2", …]"""
    refs: dict[str, list[str]] = {}
    for sc in scenarios:
        for st in sc["steps"]:
            for uid in st["unit_ids"]:
                refs.setdefault(uid, []).append(f"{sc['scenario_id']} #{st['no']}")
    return refs


# ---------- 시트 ----------

def _history(wb: Workbook, project: str, written: date) -> None:
    ws = wb.create_sheet("개정이력")
    _widths(ws, {"A": 10, "B": 14, "C": 60, "D": 22})
    ws.merge_cells("A1:D1")
    _cell(ws, "A1", f"개정 이력 — {project}", bold=True, align=CENTER)
    _box(ws, "A1:D1")
    for col, h in zip("ABCD", ("버전", "일자", "내용", "작성자")):
        _cell(ws, f"{col}2", h, bold=True, fill=HEAD_FILL, align=CENTER)
    _cell(ws, "A3", "1.0", align=CENTER)
    _cell(ws, "B3", written, align=CENTER, fmt=DATE_FORMAT)
    _cell(ws, "C3", "④ 시나리오 합성으로 처음 만듦 (예상결과는 기획서 기준)")
    _cell(ws, "D3", WRITER)


def _toc(wb: Workbook, menus: list[tuple[str, str, list[dict]]], written: date) -> None:
    """menus: [(시트 이름, DEPTH(1), 시나리오들)]"""
    ws = wb.create_sheet("00. 목차")
    widths = {"A": 24, "B": 18, "C": 26, "D": 10, "E": 10, "F": 12, "G": 10, "H": 14}
    _widths(ws, widths)
    ws.merge_cells("A1:H1")
    _cell(ws, "A1", "목차", bold=True, align=CENTER)
    _box(ws, "A1:H1")
    heads = {"A2": "메뉴명", "B2": "목차구분", "D2": "시나리오 수", "E2": "단계 수", "F2": "목차번호", "G2": "작성여부",
             "H2": "작성일자", "B3": "DEPTH(1)", "C3": "DEPTH(2)"}
    for ref, h in heads.items():
        _cell(ws, ref, h, bold=True, fill=HEAD_FILL, align=CENTER)
    for area in ("A2:A3", "B2:C2", "D2:D3", "E2:E3", "F2:F3", "G2:G3", "H2:H3"):
        ws.merge_cells(area)
        _box(ws, area)
    r = 4
    for i, (title, depth1, scenarios) in enumerate(menus, 1):
        depth2s = list(dict.fromkeys(sc["depth2"] for sc in scenarios))
        for j, d2 in enumerate(depth2s, 1):
            mine = [sc for sc in scenarios if sc["depth2"] == d2]
            _cell(ws, f"A{r}", title if j == 1 else "")
            _cell(ws, f"B{r}", f"{depth1} (01)" if j == 1 else "")
            _cell(ws, f"C{r}", f"{d2} ({j:02d})")
            _cell(ws, f"D{r}", len(mine), align=CENTER)
            _cell(ws, f"E{r}", sum(len(sc["steps"]) for sc in mine), align=CENTER)
            _cell(ws, f"F{r}", int(f"{i}01{j:02d}"), align=CENTER)
            _cell(ws, f"G{r}", "O", align=CENTER)
            _cell(ws, f"H{r}", written, align=CENTER, fmt=DATE_FORMAT)
            r += 1
    ws.freeze_panes = "A4"
    _print_setup(ws)


def _spec_sheet(wb: Workbook, title: str, depth1: str, scenarios: list[dict], project: str, written: date) -> None:
    ws = wb.create_sheet(title)
    _widths(ws, SPEC_WIDTHS)
    # 정보 칸 (기업 양식 1~2행)
    for ref, h in {"A1": "프로젝트명", "G1": "사양서작성자", "I1": "테스트확인자",
                   "A2": "시험대상 메뉴명", "G2": "사양서작성일", "I2": "테스트시행일"}.items():
        _cell(ws, ref, h, bold=True, fill=INFO_FILL, align=CENTER)
    ws.merge_cells("B1:F1")
    ws.merge_cells("B2:F2")
    _cell(ws, "B1", project)
    _cell(ws, "B2", depth1)
    _box(ws, "B1:F1")
    _box(ws, "B2:F2")
    _cell(ws, "H1", WRITER, align=CENTER)
    _cell(ws, "H2", written, align=CENTER, fmt=DATE_FORMAT)
    for ref in ("J1", "J2", "K1", "K2", "L1", "L2"):
        _cell(ws, ref, "")
    # 머리글 두 줄 (기업 양식 4~5행)
    heads = {"A4": "시험번호", "A5": "시나리오명", "B4": "시험구분", "B5": "DEPTH(1)", "C5": "DEPTH(2)", "D4": "No",
             "E4": "시험절차", "F4": "예상결과", "G4": "시험데이터", "G5": "계정", "H5": "입력값", "I5": "비고",
             "J4": "확인결과", "K4": "근거 요구사항", "L4": "데이터 출처"}
    for ref, h in heads.items():
        _cell(ws, ref, h, bold=True, fill=HEAD_FILL, align=CENTER)
    for area in ("B4:C4", "D4:D5", "E4:E5", "F4:F5", "G4:I4", "J4:J5", "K4:K5", "L4:L5"):
        ws.merge_cells(area)
        _box(ws, area)

    r = SPEC_FIRST_ROW
    for sc in scenarios:
        for k, st in enumerate(sc["steps"]):
            color = SETUP_COLOR if st["setup"] else None
            note = st["note"] or ("준비 단계" if st["setup"] else "-")
            values = [
                f"{sc['scenario_id']}\n{sc['title']}" if k == 0 else sc["scenario_id"],
                sc["depth1"], sc["depth2"], st["no"], st["action"], st["expected"],
                st["account"] or "-", st["input"] or "-", note, "",
                ", ".join(st["unit_ids"]) or "-", DATA_SOURCE.get(st["data_source"], st["data_source"]) or "-",
            ]
            for col, v in zip("ABCDEFGHIJKL", values):
                center = col in ("D", "J", "L")
                _cell(ws, f"{col}{r}", v, align=CENTER if center else WRAP,
                      color=color if col in ("E", "F") else None, bold=(col == "A" and k == 0))
            r += 1
    if r > SPEC_FIRST_ROW:
        dv = DataValidation(type="list", formula1='"O,X"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"J{SPEC_FIRST_ROW}:J{r - 1}")
    ws.freeze_panes = f"A{SPEC_FIRST_ROW}"
    _fit_rows(ws, SPEC_FIRST_ROW, SPEC_WIDTHS)
    _print_setup(ws, "4:5")


def _table(wb: Workbook, title: str, header: list[str], rows: list[list], widths: dict[str, float]) -> None:
    ws = wb.create_sheet(title)
    _widths(ws, widths)
    cols = [chr(ord("A") + i) for i in range(len(header))]
    for col, h in zip(cols, header):
        _cell(ws, f"{col}1", h, bold=True, fill=HEAD_FILL, align=CENTER)
    for r, row in enumerate(rows, 2):
        for col, v in zip(cols, row):          # 값이 없으면 "-", 사람이 채울 칸("")은 비워 둔다
            _cell(ws, f"{col}{r}", "-" if v is None else v)
    ws.freeze_panes = "A2"
    _fit_rows(ws, 2, widths)
    _print_setup(ws, "1:1")


def write_spec(path: Path, scenarios: list[dict], requirements: dict, *, project: str, written: date,
               uncovered: set[str] = frozenset(), excluded: set[str] = frozenset(),
               not_run: set[str] = frozenset()) -> Path:
    names = {s["screen_id"]: s.get("name") or "" for s in (requirements.get("app_profile") or {}).get("screens", [])
             if isinstance(s, dict) and s.get("screen_id")}
    units = [u for u in requirements.get("units", []) if isinstance(u, dict) and u.get("id")]
    refs = _step_refs(scenarios)

    wb = Workbook()
    wb.remove(wb.active)
    _history(wb, project, written)
    used = {"개정이력", "00. 목차", "확인 질문", "추적표"}
    depth1s = list(dict.fromkeys(sc["depth1"] for sc in scenarios))
    menus = [(sheet_title(f"{i:02d}. {d1}", used), d1, [sc for sc in scenarios if sc["depth1"] == d1])
             for i, d1 in enumerate(depth1s, 1)]
    _toc(wb, menus, written)
    for title, d1, mine in menus:
        _spec_sheet(wb, title, d1, mine, project, written)

    questions = sorted(requirements.get("questions", []), key=lambda q: 0 if q.get("priority") == "상" else 1)
    qrows = [["질문", q.get("id"), _screen_label(_question_screen(q.get("id")), names), q.get("priority"), q.get("topic"),
              q.get("question"), q.get("why"), ", ".join(q.get("related_units") or []),
              ", ".join(r for u in (q.get("related_units") or []) for r in refs.get(u, [])), ""]
             for q in questions]
    qrows += [["단위 확인", u["id"], _screen_label(u.get("screen_id"), names), "-", u.get("then"), u.get("issue"),
               u.get("quote"), u["id"], ", ".join(refs.get(u["id"], [])), ""]
              for u in units if (u.get("issue") or "").strip()]
    _table(wb, "확인 질문", ["구분", "번호", "화면", "우선순위", "주제", "내용", "근거·이유", "관련 요구사항", "관련 시험 단계", "답변"], qrows,
           {"A": 10, "B": 18, "C": 22, "D": 9, "E": 28, "F": 44, "G": 44, "H": 20, "I": 24, "J": 30})

    trows = []
    for u in units:
        if u["id"] in excluded:
            remark = "사양서 대상 아님 (제약: 화면에서 확인할 수 없는 처리 방식이라 정합성 판정에만 씀)"
        elif u["id"] in uncovered:
            remark = "사양서에 없음 (④가 이 단위를 확인하는 단계를 만들지 못함)"
        elif u["id"] in not_run:
            remark = "아직 사양서를 만들지 않은 화면 (scenario를 이 화면 묶음까지 돌리면 채워짐)"
        else:
            remark = ""
        trows.append([u["id"], _screen_label(u.get("screen_id"), names), u.get("kind"), u.get("origin"), u.get("then"),
                      ", ".join(u.get("source") or []), ", ".join(refs.get(u["id"], [])), remark])
    _table(wb, "추적표", ["요구사항 ID", "화면", "종류", "명시/함의", "요구사항", "기획서 위치", "시나리오·단계", "비고"], trows,
           {"A": 20, "B": 22, "C": 8, "D": 9, "E": 44, "F": 28, "G": 30, "H": 36})

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _question_screen(qid: str | None) -> str | None:
    """질문 ID에서 화면을 읽는다. Q-APP-01 → APP, Q-LOGIN-001-03 → LOGIN-001"""
    if not qid or not qid.startswith("Q-"):
        return None
    body = qid[2:]
    return "APP" if body.startswith("APP") else re.sub(r"-\d+$", "", body)
