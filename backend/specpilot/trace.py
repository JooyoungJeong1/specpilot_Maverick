"""trace: 단위 하나(또는 기획서 항목 하나)를 기획서 원문 → ② 단위 → ③ 판정·근거 코드까지 한 번에 보여 준다.

③④ 결과가 틀렸을 때 원인이 어느 단계인지 가려내는 데 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import code_prep, pdf_utils, schema
from .stages import read_json

QUESTIONS = [
    ("기획서 항목이 ② 결과에 있나", "② 누락 (또는 ①이 화면 페이지를 잘못 묶음)"),
    ("단위 내용(then, exact)이 기획서 원문과 같나", "② 읽기 오류"),
    ("단위 하나에 결과가 하나인가", "② 쪼개기 문제 (덜 쪼갬)"),
    ("판정에 필요한 코드가 ③ 입력에 들어갔나", "코드 묶기 문제"),
]
LAST = "1~4가 모두 '예'인데 판정이 틀렸다면 ③ 프롬프트 문제"


def _find_units(requirements: dict, unit: str | None, item: str | None) -> list[dict]:
    if unit:
        return [u for u in requirements["units"] if u.get("id") == unit]
    return [u for u in requirements["units"] if item in schema.item_keys(u)]


def _item_text(run_dir: Path, requirements: dict, item_key: str) -> str | None:
    sid, _, item = item_key.partition(" ")
    screen = next((s for s in requirements["app_profile"].get("screens", []) if s["screen_id"] == sid), None)
    pdf = run_dir / "input.pdf"
    if not screen or not pdf.exists():
        return None
    for p in screen.get("pages", []):
        block = pdf_utils.item_text(pdf, p, item)
        if block:
            return f"(p.{p})\n{block}"
    return None


def trace(run_dir: Path, unit: str | None = None, item: str | None = None) -> str:
    run_dir = Path(run_dir)
    requirements = read_json(run_dir / "requirements.json")
    units = _find_units(requirements, unit, item)
    lines: list[str] = []
    if not units:
        target = unit or item
        lines.append(f"'{target}'에 해당하는 단위가 없습니다.")
        if item:
            lines.append(f"→ 질문 1 '아니오': {QUESTIONS[0][1]}")
            text = _item_text(run_dir, requirements, item)
            if text:
                lines += ["", "[기획서 원문]", text]
        return "\n".join(lines)

    judgments = read_json(run_dir / "judgments.json") if (run_dir / "judgments.json").exists() else None
    judge_run = read_json(run_dir / "judge" / "run.json") if (run_dir / "judge" / "run.json").exists() else None
    cb = code_prep.load_codebase(Path(judge_run["code_root"])) if judge_run and Path(judge_run["code_root"]).exists() else None

    for u in units:
        lines.append("=" * 70)
        lines.append(f"{u['id']}  ({u.get('kind')}, {u.get('origin')})")
        lines.append("=" * 70)

        lines.append("[1. 기획서 원문]")
        for key in schema.item_keys(u):
            text = _item_text(run_dir, requirements, key)
            lines.append(f"- {key}")
            if text:
                lines += ["    " + t for t in text.splitlines()]
        lines.append(f"  quote: {u.get('quote')}")
        if u.get("reason"):
            lines.append(f"  함의 근거: {u['reason']}")

        lines.append("[2. ② 단위]")
        for f in ("given", "when", "conditions", "then", "exact", "issue", "ref_hint"):
            lines.append(f"  {f}: {json.dumps(u.get(f), ensure_ascii=False)}")

        lines.append("[3. ③ 판정]")
        r = (judgments or {}).get("results", {}).get(u["id"])
        if not r:
            lines.append("  판정 결과 없음 (judge를 아직 안 돌림)")
        else:
            lines.append(f"  status: {r['status']}" + (f"  (원래 {r['original_status']})" if r.get("original_status") else ""))
            for m in r.get("mismatch", []):
                lines.append(f"  다른 점: {json.dumps(m, ensure_ascii=False)}")
            if r.get("note"):
                lines.append(f"  note: {r['note']}")
            if r.get("split_issue"):
                lines.append(f"  ※ 판정 갈림(덜 쪼갠 신호): {r['split_issue']}")
            for p in r.get("evidence_problems", []):
                lines.append(f"  ※ 근거 문제: {p}")
            for ev in r.get("evidence", []):
                lines.append(f"  근거 {ev.get('file')}:{ev.get('line')}")
                if (cb and ev.get("file") in cb.files and isinstance(ev.get("line"), int)
                        and 1 <= ev["line"] <= len(cb.files[ev["file"]])):
                    lines.append(code_prep.snippet(cb, ev["file"], ev["line"]))
            meta_path = run_dir / "judge" / f"{r.get('screen_id')}.meta.json"
            if meta_path.exists():
                meta = read_json(meta_path)
                files = meta.get("files")
                lines.append(f"  ③ 입력: {'코드 전체' if files is None else f'화면별 묶음 {len(files)}개 파일'}")

        lines.append("[4. ④ 테스트 단계]")
        lines.append("  ④ 결과 없음 (아직 미구현)")

        lines.append("[원인 가려내기]")
        auto = {0: "단위가 있음 → 예",
                2: "③이 판정 갈림을 표시함 → 아니오" if r and r.get("split_issue") else None}
        for i, (q, cause) in enumerate(QUESTIONS):
            hint = auto.get(i)
            lines.append(f"  {i + 1}. {q}?  '아니오'면 {cause}" + (f"   ← {hint}" if hint else ""))
        lines.append(f"  5. {LAST}")
        lines.append("")
    return "\n".join(lines)
