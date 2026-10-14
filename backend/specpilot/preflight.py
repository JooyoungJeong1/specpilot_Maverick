"""입력 점검과 게이트 판정. LLM을 쓰지 않는다.

입력 점검 (run_preflight): ① 앞에서 기획서 PDF만 보고 판단한다.
  - PDF가 열리는지, 글자층이 있는지(스캔본이 아닌지), 설명표 번호를 찾을 수 있는지(지원 양식인지)
  - 쪽마다 설명 번호가 빈틈없이 이어지는지
  - 설명표의 번호가 화면 그림 속 마커로도 있는지 (그림이 잘렸거나 번호가 어긋났는지)
  기획서가 통째로 깨졌으면 여기서 전체를 반려한다. 그 밖의 문제는 경고로 남긴다.

게이트 판정 (gate_screens): ① 결과(화면↔쪽 대응)를 받아 화면 단위로 묶어 판단한다.
  - 그림 마커와 설명 번호가 많이 어긋난 화면은 반려 (② 를 돌리지 않음)
  - 반려된 화면이 많으면 전체 반려
  - 어느 화면에도 속하지 않은 쪽, 설계서에 없는 화면으로 가는 이동은 경고
"""
from __future__ import annotations

import re
from pathlib import Path

from pypdf import PdfReader

from . import pdf_utils

PASS, WARN, REJECT = "통과", "경고", "반려"
SCREEN_ID = re.compile(r"[A-Z][A-Z0-9]*-\d{2,}")


def _gaps(numbers: list[int]) -> list[int]:
    return [n for n in range(min(numbers), max(numbers) + 1) if n not in numbers] if numbers else []


def _letter_gaps(letters: list[str]) -> list[str]:
    if not letters:
        return []
    return [chr(c) for c in range(ord("A"), ord(max(letters)) + 1) if chr(c) not in letters]


def _desc_numbers(items: list[str]) -> list[int]:
    return [int(i.split()[1]) for i in items if i.startswith("Description ")]


def _action_letters(items: list[str]) -> list[str]:
    return [i.split()[1] for i in items if i.startswith("Action ")]


# ---------- 입력 점검 ----------

def run_preflight(pdf_path: Path, marker_match_min: float = 0.5, reject_ratio: float = 0.5) -> dict:
    pdf_path = Path(pdf_path)
    report: dict = {"verdict": PASS, "reasons": [], "warnings": [], "extractor": pdf_utils.text_extractor(),
                    "page_count": 0, "pages": {},
                    "settings": {"marker_match_min": marker_match_min, "reject_ratio": reject_ratio}}

    def reject(msg: str) -> dict:
        report["verdict"] = REJECT
        report["reasons"].append(msg)
        return report

    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted and not reader.decrypt(""):
            return reject("암호가 걸린 PDF라 읽을 수 없습니다")
        total = len(reader.pages)
    except Exception as e:  # 깨진 파일, PDF가 아닌 파일
        return reject(f"PDF를 열 수 없습니다: {e}")
    report["page_count"] = total
    if total == 0:
        return reject("쪽이 하나도 없는 PDF입니다")

    layouts = pdf_utils.read_layout(pdf_path)
    strong = layouts is not None and len(layouts) == total
    if not strong:
        report["extractor"] = "pypdf"
        report["warnings"].append("pdftotext(poppler)가 없거나 글자 좌표를 읽지 못해, 항목 번호를 덜 찾고 그림 마커 검사를 "
                                  "건너뜁니다. poppler를 설치하면 정확해집니다")

    pages: dict[str, dict] = {}
    for p in range(1, total + 1):
        if strong:
            lay = layouts[p - 1]
            chars = lay.char_count
            items = lay.item_names()
        else:
            chars = len(pdf_utils.squash(pdf_utils._pypdf_text(pdf_path, p, layout=False)))
            items = sorted(pdf_utils.detect_items(pdf_utils.page_text(pdf_path, p)))
        # notes: 번호 자체의 문제(빈 번호, 중복, 대조 불가). 그림 마커 대조 결과는 따로 필드에 둔다.
        info: dict = {"chars": chars, "items": items, "status": PASS, "notes": [], "marker_match": None}
        nums, letters = _desc_numbers(items), _action_letters(items)
        if strong and items:
            gaps, lgaps = _gaps(nums), _letter_gaps(letters)
            dups = sorted({i for i in items if items.count(i) > 1})
            info.update(numbering_gaps=[f"Description {n}" for n in gaps] + [f"Action {c}" for c in lgaps],
                        duplicates=dups,
                        picture_numbers=sorted(lay.picture_numbers), picture_letters=sorted(lay.picture_letters),
                        missing_in_picture=[], letters_missing_in_picture=[])
            if info["numbering_gaps"]:
                info["notes"].append(f"설명 번호가 비어 있음: {', '.join(info['numbering_gaps'])}")
            if dups:
                info["notes"].append(f"같은 번호가 두 번 나옴: {', '.join(dups)}")
            targets = sorted({n for n in nums if n >= 1})
            if targets and lay.picture_numbers:
                missing = [n for n in targets if n not in lay.picture_numbers]
                info["marker_match"] = round((len(targets) - len(missing)) / len(targets), 3)
                info["missing_in_picture"] = [f"Description {n}" for n in missing]
                if info["marker_match"] < marker_match_min:
                    info["status"] = "반려후보"
            elif targets:
                info["notes"].append("그림 속 마커가 글자가 아니라서 마커 대조를 못 함")
            if lay.picture_letters:
                info["letters_missing_in_picture"] = [f"Action {c}" for c in sorted(set(letters))
                                                      if c not in lay.picture_letters]
            if info["status"] == PASS and (info["notes"] or info["missing_in_picture"] or info["letters_missing_in_picture"]):
                info["status"] = WARN
        pages[str(p)] = info
    report["pages"] = pages

    # 문서 전체 판단
    no_text = [int(p) for p, i in pages.items() if i["chars"] == 0]
    if len(no_text) >= max(1, reject_ratio * total):
        return reject(f"글자층이 없는 쪽이 {len(no_text)}/{total}쪽입니다. 스캔 이미지 PDF로 보여 읽을 수 없습니다")
    if no_text:
        report["warnings"].append(f"글자층이 없는 쪽: {', '.join(f'p.{p}' for p in no_text)}")

    item_pages = [p for p, i in pages.items() if i["items"]]
    if not item_pages:
        msg = "설명표(Description·Action 번호)를 한 곳도 찾지 못했습니다. 지원하지 않는 기획서 양식일 수 있습니다"
        if strong:
            return reject(msg)
        report["warnings"].append(msg)       # pypdf는 원래 덜 찾으므로 반려하지 않는다

    checked = [p for p, i in pages.items() if i.get("marker_match") is not None]
    bad = [p for p in checked if pages[p]["status"] == "반려후보"]
    if bad and len(bad) >= reject_ratio * len(checked):
        return reject(f"그림 마커와 설명 번호가 맞지 않는 쪽이 {len(bad)}/{len(checked)}쪽입니다 "
                      f"({', '.join('p.' + p for p in bad)})")
    return report


def checklist(preflight: dict | None, pages: list[int]) -> set[str] | None:
    """화면 페이지들의 기획서 항목 번호. 입력 점검 결과가 없으면 None."""
    if not preflight or not preflight.get("pages"):
        return None
    out: set[str] = set()
    for p in pages:
        out |= set(preflight["pages"].get(str(p), {}).get("items", []))
    return out


# ---------- 게이트 판정 (① 이후) ----------

def gate_screens(preflight: dict | None, profile: dict, marker_match_min: float = 0.5,
                 reject_ratio: float = 0.5) -> dict:
    screens = profile.get("screens", []) or []
    pages_info = (preflight or {}).get("pages", {})
    gate: dict = {"verdict": PASS, "reasons": [], "screens": {}, "warnings": [],
                  "reading_notes": profile.get("reading_notes", []) or []}

    notes_by_screen: dict[str, list[str]] = {}
    for n in gate["reading_notes"]:
        if isinstance(n, dict) and n.get("note"):
            notes_by_screen.setdefault(str(n.get("screen_id")), []).append(str(n["note"]))

    for s in screens:
        sid = s.get("screen_id")
        repeats = set(((s.get("repeats_from") or {}).get("items") or []) if isinstance(s.get("repeats_from"), dict) else [])
        result: dict = {"verdict": PASS, "reasons": [], "warnings": []}
        matched = total = 0
        missing: list[str] = []
        for p in s.get("pages", []) or []:
            info = pages_info.get(str(p))
            if not info:
                continue
            result["warnings"] += [f"p.{p} {n}" for n in info.get("notes", [])]
            if info.get("marker_match") is None:
                continue
            pic = set(info.get("picture_numbers", []))
            targets = [i for i in info["items"] if i.startswith("Description ") and i != "Description 0" and i not in repeats]
            total += len(targets)
            for t in targets:
                if int(t.split()[1]) in pic:
                    matched += 1
                else:
                    missing.append(t)
            lmiss = [a for a in info.get("letters_missing_in_picture", []) if a not in repeats]
            if lmiss:
                result.setdefault("letters_missing", []).extend(lmiss)
                result["warnings"].append(f"p.{p} 그림에 없는 Action: {', '.join(lmiss)}")
        if total:
            ratio = round(matched / total, 3)
            result["marker_match"] = ratio
            result["missing_in_picture"] = missing
            if ratio < marker_match_min:
                result["verdict"] = REJECT
                result["reasons"].append(f"그림에서 찾을 수 없는 설명 번호가 많습니다 ({matched}/{total} 일치, "
                                         f"없음: {', '.join(missing)})")
            elif missing:
                result["warnings"].append(f"그림에 없는 설명 번호: {', '.join(missing)} (그림이 잘렸을 수 있음)")
        result["warnings"] += [f"① 메모: {n}" for n in notes_by_screen.get(str(sid), [])]
        if result["verdict"] == PASS and result["warnings"]:
            result["verdict"] = WARN
        gate["screens"][sid] = result

    # 어느 화면에도 속하지 않은 쪽 (글자가 있는 쪽만)
    assigned = set()
    for s in screens:
        assigned |= set(s.get("pages", []) or []) | set(s.get("state_pages", []) or [])
    unassigned = [int(p) for p, i in pages_info.items() if int(p) not in assigned and i.get("chars", 0) > 0]
    if unassigned:
        gate["warnings"].append(f"어느 화면에도 속하지 않은 쪽: {', '.join(f'p.{p}' for p in sorted(unassigned))}")

    # 이동 대상 (데드엔드): 반려하지 않고 알리기만 한다. ②가 그 단위의 issue로 적는다.
    ids = {s.get("screen_id") for s in screens}
    for f in profile.get("flows", []) or []:
        if not isinstance(f, dict):
            continue
        to = str(f.get("to") or "")
        found = SCREEN_ID.findall(to)
        label = f"{f.get('from')} '{f.get('trigger')}' → '{to}'"
        if not found:
            gate["warnings"].append(f"이동 대상에 화면 ID가 없음: {label} (외부 화면이거나 설계서에 없는 화면)")
        elif any(t not in ids for t in found):
            gate["warnings"].append(f"설계서에 없는 화면 ID로 이동: {label}")

    rejected = [sid for sid, r in gate["screens"].items() if r["verdict"] == REJECT]
    if rejected and screens and len(rejected) >= reject_ratio * len(screens):
        gate["verdict"] = REJECT
        gate["reasons"].append(f"반려된 화면이 {len(rejected)}/{len(screens)}개입니다: {', '.join(rejected)}")
    return gate


# ---------- 콘솔 출력 ----------

def format_preflight(report: dict) -> str:
    items = sum(len(i.get("items", [])) for i in report.get("pages", {}).values())
    lines = [f"[입력 점검] {report['verdict']} · {report.get('page_count', 0)}쪽 · 기획서 항목 {items}개 ({report['extractor']})"]
    lines += [f"  × {r}" for r in report["reasons"]]
    lines += [f"  ! {w}" for w in report["warnings"]]
    for p, info in report.get("pages", {}).items():
        for n in info.get("notes", []):
            lines.append(f"  ! p.{p} {n}")
        if info.get("missing_in_picture"):
            mark = "×" if info["status"] == "반려후보" else "!"
            lines.append(f"  {mark} p.{p} 그림에 없는 설명 번호: {', '.join(info['missing_in_picture'])} "
                         f"(일치 {info['marker_match']:.0%})")
        if info.get("letters_missing_in_picture"):
            lines.append(f"  ! p.{p} 그림에 없는 Action: {', '.join(info['letters_missing_in_picture'])}")
    return "\n".join(lines)


def format_gate(gate: dict) -> str:
    screens = gate.get("screens", {})
    rejected = [sid for sid, r in screens.items() if r["verdict"] == REJECT]
    lines = [f"[게이트] {gate['verdict']} · 화면 {len(screens)}개 중 반려 {len(rejected)}개"]
    lines += [f"  × {r}" for r in gate["reasons"]]
    for sid, r in screens.items():
        for reason in r["reasons"]:
            lines.append(f"  × {sid} 반려: {reason}")
        for w in r["warnings"]:
            lines.append(f"  ! {sid} {w}")
    lines += [f"  ! {w}" for w in gate["warnings"]]
    return "\n".join(lines)
