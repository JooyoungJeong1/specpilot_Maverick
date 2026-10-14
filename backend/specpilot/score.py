"""score: ③ 판정을 조장이 가진 정답 세트와 비교해 점수를 낸다.

비교는 기획서 항목 단위("LOGIN-001 Description 3")로 한다. 단위를 몇 개로 쪼갰든 같은 기준으로 채점하려는 것이다.
정답 세트는 팀 저장소에 올리지 않는다 (블라인드 평가).

채점 규칙
- 항목 판정은 **명시 단위만** 모아서 계산한다. 정답 세트는 기획서에 적힌 것만 보고 정했기 때문이다.
  함의 단위를 넣으면 근거 항목 여러 개에 판정이 퍼져서, 추론이 맞아도 오탐으로 잡힌다.
- 함의 단위는 채점하지 않고 '함의 검토' 목록으로 따로 낸다. 사람이 (1) 추론이 기획서로 정당한지
  (2) ③ 판정이 맞는지를 본다.
- 판정이 없는 항목은 이유를 붙인다 (함의로만 나옴, 질문으로 감, skipped, 검사에서 빠짐, 화면 반려 등).
  명시 내용을 함의·질문으로 잘못 분류하면 여기서 드러난다. 반대로 지어낸 내용을 명시로 붙이면 오탐으로 드러난다.

정답 세트 형식 (docs/answer_key.example.json 참고):
{"items": {"LOGIN-001 Description 2": {"expected": "미구현", "note": "..."}, ...}}
expected: 구현 / 불일치 / 미구현 / 부분구현 / 확인필요. 정답 세트에 없는 항목은 채점하지 않는다.
"""
from __future__ import annotations

from pathlib import Path

from . import schema
from .stages import read_json, write_json

DEFECT = {"불일치", "미구현", "부분구현"}
VALID = DEFECT | {"구현", "확인필요"}
EXPLICIT = "명시"


def load_key(path: Path) -> dict[str, dict]:
    obj = read_json(Path(path))
    items = obj.get("items", obj)
    out = {}
    for key, v in items.items():
        if key.startswith("_"):
            continue
        expected = v.get("expected") if isinstance(v, dict) else v
        if expected not in VALID:
            raise ValueError(f"정답 세트 '{key}'의 expected 값이 잘못됐습니다: {expected}")
        out[key] = {"expected": expected, "note": v.get("note") if isinstance(v, dict) else None}
    return out


def _keys(screen_id: str, source) -> list[str]:
    src = source if isinstance(source, list) else [source]
    return schema.item_keys({"screen_id": screen_id, "source": [s for s in src if s]})


def _where_did_it_go(requirements: dict, judged_ids: set) -> dict[str, list[str]]:
    """명시 판정이 없는 항목을 설명하기 위해, 항목 → 그 항목을 가리키는 다른 흔적 목록을 만든다."""
    trace: dict[str, list[str]] = {}

    def add(keys, why):
        for k in keys:
            trace.setdefault(k, [])
            if why not in trace[k]:
                trace[k].append(why)

    for u in requirements.get("units", []):
        keys = _keys(u.get("screen_id", ""), u.get("source"))
        if u.get("origin") != EXPLICIT:
            add(keys, f"함의 단위로만 나옴 ({u.get('id')})")
        elif u.get("id") not in judged_ids:
            add(keys, f"명시 단위는 있지만 ③ 판정이 없음 ({u.get('id')})")
    for q in requirements.get("questions", []):
        d = q.get("draft_unit") or {}
        if d:
            add(_keys(d.get("screen_id", ""), d.get("source")), f"함의였다가 근거가 약해 질문으로 옮겨짐 ({q.get('id')})")
    for sid, rows in (requirements.get("skipped") or {}).items():
        for r in rows or []:
            add(_keys(sid, r.get("source")), f"②가 skipped로 둠: {r.get('reason')}")
    for sid, rej in (requirements.get("rejected_units") or {}).items():
        for u in rej.get("units", []) or []:
            add(_keys(u.get("screen_id", sid), u.get("source")), "검사를 통과하지 못해 빠진 단위 (rejected)")
    for sid, reason in (requirements.get("rejected_screens") or {}).items():
        trace.setdefault(f"__screen__{sid}", []).append(f"화면 반려: {reason}")
    return trace


def _reason_not_judged(item: str, trace: dict, requirements: dict) -> str:
    sid = item.split(" ")[0]
    found = trace.get(item)
    if found:
        return "; ".join(found)
    if f"__screen__{sid}" in trace:
        return trace[f"__screen__{sid}"][0]
    status = (requirements.get("screen_status") or {}).get(sid, {}).get("status")
    if status and status != "완료":
        return f"화면 상태 '{status}'"
    return "②가 이 항목으로 단위를 만들지 않음 (질문으로 갔는지 questions를 확인)"


def score(run_dir: Path, key_path: Path) -> dict:
    run_dir = Path(run_dir)
    key = load_key(key_path)
    judgments = read_json(run_dir / "judgments.json")
    results = judgments.get("results", {}) or {}
    req_path = run_dir / "requirements.json"
    requirements = read_json(req_path) if req_path.exists() else {}
    units = requirements.get("units", [])

    if units and results:
        verdicts = {uid: r["status"] for uid, r in results.items()}
        explicit = [u for u in units if u.get("origin") == EXPLICIT and u.get("id") in verdicts]
        judged = schema.aggregate_items(explicit, verdicts)
        trace = _where_did_it_go(requirements, set(verdicts))
    else:                                    # requirements.json이 없는 예전 실행: ③이 모은 항목 판정을 그대로 쓴다
        judged = judgments.get("items", {})
        trace = {}

    rows = []
    for item, k in key.items():
        got = judged.get(item, {})
        predicted = got.get("status")
        exp_defect, pred_defect = k["expected"] in DEFECT, predicted in DEFECT
        if exp_defect and pred_defect:
            outcome = "탐지"
        elif exp_defect:
            outcome = "놓침"
        elif pred_defect:
            outcome = "오탐"
        else:
            outcome = "정상"
        row = {"item": item, "expected": k["expected"], "predicted": predicted, "outcome": outcome,
               "units": got.get("units", []), "note": k["note"]}
        if predicted is None:
            row["why_not_judged"] = _reason_not_judged(item, trace, requirements) if requirements else "판정 없음"
        rows.append(row)

    implied = []
    for u in units:
        if u.get("origin") == EXPLICIT:
            continue
        r = results.get(u.get("id"), {})
        implied.append({
            "unit_id": u.get("id"), "screen_id": u.get("screen_id"), "source": u.get("source"),
            "quote": u.get("quote"), "reason": u.get("reason"), "then": u.get("then"),
            "verdict": r.get("status"), "evidence": r.get("evidence"), "judge_note": r.get("note"),
            "추론이_정당한가": None, "판정이_맞나": None,          # 사람이 채운다 (O / X)
        })

    def n(cond):
        return sum(1 for r in rows if cond(r))

    defects = n(lambda r: r["expected"] in DEFECT)
    flagged = n(lambda r: r["predicted"] in DEFECT)
    tp = n(lambda r: r["outcome"] == "탐지")
    summary = {
        "items_in_key": len(rows),
        "defects_in_key": defects,
        "detected": tp,
        "recall": round(tp / defects, 3) if defects else None,                 # 결함 탐지율
        "false_alarms": n(lambda r: r["outcome"] == "오탐"),
        "precision": round(tp / flagged, 3) if flagged else None,              # 결함이라고 한 것 중 맞은 비율
        "exact_match": round(n(lambda r: r["predicted"] == r["expected"]) / len(rows), 3) if rows else None,
        "needs_review": n(lambda r: r["predicted"] == "확인필요"),
        "not_judged": n(lambda r: r["predicted"] is None),
        "implied_units": len(implied),
        "basis": "명시 단위만" if units and results else "③ 항목 판정 그대로",
    }
    report = {"summary": summary, "rows": rows, "implied_review": implied}
    write_json(run_dir / "score_report.json", report)
    unit_by_id = {u.get("id"): u for u in units}
    (run_dir / "score_review.md").write_text(_review_md(rows, unit_by_id, results), encoding="utf-8")
    (run_dir / "implied_review.md").write_text(_implied_md(implied), encoding="utf-8")
    return report


def _implied_md(implied: list[dict]) -> str:
    """함의 단위 검토지. 정답 세트 내용이 없으니 프롬프트 담당과 공유해도 된다."""
    out = ["# 함의 단위 검토 (O / X 를 채운다)", "",
           "- **추론이 정당한가**: 근거 원문 두 곳을 합치면 정말 이 동작이 따라 나오는가 (기획서만 보고 판단)",
           "- **판정이 맞나**: ③의 판정과 근거 코드가 맞는가 (코드를 열어 확인)", ""]
    for i in implied:
        out += [f"## {i['unit_id']} ({i['screen_id']})", "",
                f"- 근거 항목: {', '.join(i['source']) if isinstance(i['source'], list) else i['source']}",
                f"- 근거 원문: {i.get('quote') or ''}",
                f"- 추론: {i.get('reason') or ''}",
                f"- 결과(then): {i.get('then') or ''}",
                f"- ③ 판정: {i.get('verdict') or '판정 없음'}" + (f" — {i['judge_note']}" if i.get("judge_note") else "")]
        for e in i.get("evidence") or []:
            if isinstance(e, dict):
                out.append(f"  - 근거: `{e.get('file')}:{e.get('line')}` {str(e.get('code') or '').strip()[:120]}")
        out += ["", "**추론이 정당한가:**   (O / X)", "", "**판정이 맞나:**   (O / X)", "", "**메모:**", ""]
    return "\n".join(out)


def _review_md(rows: list[dict], unit_by_id: dict, results: dict) -> str:
    """정답과 판정이 다른 항목만 골라, 정답(근거)과 AI 판정(단위별 근거 코드·설명)을 나란히 적는다."""
    order = {"놓침": 0, "오탐": 1}
    wrong = [r for r in rows if r["predicted"] != r["expected"]]
    wrong.sort(key=lambda r: (order.get(r["outcome"], 2 if r["predicted"] else 3), r["item"]))
    label = lambda r: (r["outcome"] if r["outcome"] in order else
                       "판정 안 됨" if r["predicted"] is None else
                       "확인필요" if r["predicted"] == "확인필요" else "종류 다름")
    out = ["# 채점 상세 — 명시 단위 기준 (조장 전용, 공유 금지)", "",
           "## 전체 항목 표", "",
           "| 항목 | 정답 | AI | 결과 |", "| --- | --- | --- | --- |"]
    for r in rows:
        mark = "" if r["predicted"] == r["expected"] else " ✗"
        out.append(f"| {r['item']} | {r['expected']} | {r['predicted'] or '판정 없음'} | {r['outcome']}{mark} |")
    out += ["", "(✗ = 판정 값이 정답과 다름. 아래에 자세히)", "",
            "# 정답과 다른 항목 자세히", "",
            f"{len(wrong)}개. 순서: 놓침 → 오탐 → 종류 다름·확인필요 → 판정 안 됨", ""]
    for r in wrong:
        out += [f"## [{label(r)}] {r['item']}", "",
                f"- **정답: {r['expected']}** — {r.get('note') or ''}",
                f"- **AI: {r['predicted'] or '판정 없음'}**" +
                (f" — {r['why_not_judged']}" if r.get("why_not_judged") else "")]
        for uid in r.get("units", []):
            u, j = unit_by_id.get(uid, {}), results.get(uid, {})
            st = j.get("status", "?")
            if j.get("original_status"):
                st += f" (원래 {j['original_status']})"
            out.append(f"  - `{uid}` {st}: {u.get('then') or u.get('quote') or ''}")
            if j.get("note"):
                out.append(f"    - 설명: {j['note']}")
            for e in j.get("evidence", []) or []:
                if isinstance(e, dict):
                    out.append(f"    - 근거: `{e.get('file')}:{e.get('line')}` {str(e.get('code') or '').strip()[:120]}")
        out.append("")
    return "\n".join(out)


def format_report(report: dict) -> str:
    s = report["summary"]
    pct = lambda v: "-" if v is None else f"{v * 100:.0f}%"
    lines = [
        f"[채점] 정답 세트 항목 {s['items_in_key']}개 (결함 {s['defects_in_key']}개) · 기준: {s.get('basis', '')}",
        f"  결함 탐지율 {pct(s['recall'])} ({s['detected']}/{s['defects_in_key']}) · 오탐 {s['false_alarms']}개 · "
        f"정밀도 {pct(s['precision'])} · 판정 완전 일치 {pct(s['exact_match'])}",
        f"  확인필요로 보류 {s['needs_review']}개 · 판정 안 됨 {s['not_judged']}개",
    ]
    misses = [r for r in report["rows"] if r["outcome"] in ("놓침", "오탐")]
    if misses:
        lines.append("  틀린 항목 (trace --item 으로 원인 확인):")
        for r in misses:
            lines.append(f"    {r['outcome']}  {r['item']:<28} 정답 {r['expected']:<5} 판정 {r['predicted'] or '없음'}")
    nj = [r for r in report["rows"] if r["predicted"] is None]
    if nj:
        lines.append("  판정 안 된 항목과 이유:")
        for r in nj:
            lines.append(f"    {r['item']:<28} {r.get('why_not_judged', '')}")
    if s.get("implied_units"):
        lines.append(f"  함의 단위 {s['implied_units']}개는 채점하지 않음 → implied_review.md 에 O/X를 채운다 "
                     f"(정답 내용 없음, 프롬프트 담당과 공유 가능)")
    lines.append("  정답과 AI 판정 나란히 보기: score_review.md  (정답이 들어 있으니 공유 금지)")
    lines.append("  자세한 내용: score_report.json")
    return "\n".join(lines)
