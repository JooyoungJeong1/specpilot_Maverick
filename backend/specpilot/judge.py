"""③ 정합성 판정: 코드 묶기 → 화면마다 판정 → 근거 줄 대조 → 항목별 집계.

코드를 넣는 방식은 크기를 재서 정한다.
- whole : 코드 전체를 화면마다 같이 넣는다 (캐시돼서 두 번째 화면부터 싸다). 놓치는 파일이 없다.
- screen: 화면마다 관련 파일만 넣는다. 관련 파일은 LLM이 파일 목록을 보고 고르고(code_map.json),
          프로그램이 단위의 문구가 들어 있는 파일을 더한다. 사람이 code_map.json을 고쳐도 된다.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import code_prep, pdf_utils, schema
from .code_prep import Codebase
from .stages import (STATUS_DONE, STATUS_DRY, STATUS_FAILED, STATUS_REVIEW, RunContext,
                     _call_with_retry, _write_preview, read_json, write_json)

APP = "APP"
NO_FACTS = "(없음)"


# ---------- 코드 분석 결과 (코드팀 정적 분석) ----------

def load_facts(path: Path | None) -> dict:
    """judge --facts 로 받은 코드 분석 결과 파일. 형식은 docs/code_facts.example.json.

    {"common": [...모든 화면에 같이 줄 사실...], "screens": {"LOGIN-001": [...그 화면 사실...]}}
    항목 하나는 문자열이든 객체든 상관없다. 그대로 JSON으로 ③ 프롬프트에 들어간다.
    """
    if not path:
        return {}
    obj = read_json(Path(path))
    if not isinstance(obj, dict) or not isinstance(obj.get("screens", {}), dict) \
            or not isinstance(obj.get("common", []), list):
        raise RuntimeError(f"코드 분석 결과 형식이 다릅니다 (common은 목록, screens는 화면ID → 목록): {path}")
    return obj


def facts_for(facts: dict, sid: str) -> list:
    """그 화면에 넣을 사실: 공통 + 그 화면 것."""
    if not facts:
        return []
    return list(facts.get("common", [])) + list((facts.get("screens") or {}).get(sid, []))


# ---------- 단위 나누기 ----------

def units_by_screen(requirements: dict) -> dict[str, list[dict]]:
    """화면 단위는 그 화면으로, 앱 전체 단위는 언급된 화면으로 보낸다. 어느 화면도 언급하지 않으면 APP으로 모은다."""
    screens = [s["screen_id"] for s in requirements["app_profile"].get("screens", [])]
    out: dict[str, list[dict]] = {sid: [] for sid in screens}
    leftovers = []
    for u in requirements["units"]:
        sid = u.get("screen_id")
        if sid != APP:
            out.setdefault(sid, []).append(u)
            continue
        blob = json.dumps([u.get("source"), u.get("quote"), u.get("exact")], ensure_ascii=False)
        hits = [s for s in screens if s in blob]
        for s in hits:
            out[s].append(u)
        if not hits:
            leftovers.append(u)
    if leftovers:
        out[APP] = leftovers
    return {k: v for k, v in out.items() if v}


def _phrases(units: list[dict]) -> list[str]:
    out = []
    for u in units:
        ex = u.get("exact") or {}
        if ex.get("message"):
            out.append(ex["message"])
    return out


# ---------- 코드 묶음 ----------

def choose_mode(settings, cb: Codebase, forced: str | None) -> str:
    if forced in ("whole", "screen"):
        return forced
    return "whole" if cb.tokens() <= settings.code_token_limit else "screen"


def build_code_map(ctx: RunContext, cb: Codebase, requirements: dict, units: dict[str, list[dict]]) -> dict:
    path = ctx.run_dir / "judge" / "code_map.json"
    if path.exists():                       # 사람이 고친 대응표가 있으면 그대로 쓴다
        return read_json(path)
    screens = []
    for s in requirements["app_profile"].get("screens", []):
        us = units.get(s["screen_id"], [])
        labels = []
        for u in us:
            ex = u.get("exact") or {}
            labels += [ex.get("message"), ex.get("target")] + list(ex.get("values") or [])
        screens.append({"screen_id": s["screen_id"], "name": s.get("name"), "depth": s.get("depth"),
                        "labels": [l for l in dict.fromkeys(labels) if l][:15]})
    rendered = ctx.prompts.render(
        "code_select",
        SCREENS=json.dumps(screens, ensure_ascii=False),
        FILE_INDEX=json.dumps(code_prep.file_index(cb), ensure_ascii=False),
    )
    if ctx.dry_run:
        _write_preview(ctx, "code_select", rendered, "없음")
        return {"mapping": [], "common_files": []}

    def validate(o):
        issues = []
        if not isinstance(o.get("mapping"), list):
            issues.append(schema.Issue("error", "code_map", "mapping이 목록이 아닙니다"))
        return issues

    obj, issues, meta = _call_with_retry(ctx, "code_select", rendered, [{"type": "text", "text": rendered.user_input}], validate)
    if obj is None or schema.errors(issues):
        raise RuntimeError("화면-코드 대응표를 만들지 못했습니다. --mode whole로 돌리거나 judge/code_map.json을 직접 만드세요")
    unknown = []
    for m in obj.get("mapping", []):
        kept = [f for f in m.get("files", []) if f in cb.files]
        unknown += [f for f in m.get("files", []) if f not in cb.files]
        m["files"] = kept
    obj["common_files"] = [f for f in obj.get("common_files", []) if f in cb.files]
    obj["_dropped_unknown_files"] = unknown
    write_json(path, obj)
    write_json(ctx.run_dir / "judge" / "code_map.meta.json", meta)
    return obj


def bundle_for(sid: str, units: list[dict], cb: Codebase, code_map: dict) -> list[str]:
    files = set(code_map.get("common_files", []))
    for m in code_map.get("mapping", []):
        if m.get("screen_id") == sid:
            files |= set(m.get("files", []))
    files |= code_prep.files_mentioning(cb, _phrases(units))
    return sorted(files)


# ---------- 화면 하나 판정 ----------

def judge_screen(ctx: RunContext, cb: Codebase, sid: str, units: list[dict], paths: list[str] | None,
                 facts: list | None = None) -> dict:
    unit_ids = [u["id"] for u in units]
    scope = ("전체 코드다." if paths is None else
             "이 화면과 관련된 파일만 골라 넣은 묶음이다. 필요한 코드가 묶음에 없어 보이면 미구현이 아니라 "
             "확인필요로 하고 note에 어떤 파일이 더 필요한지 적는다.")
    # ②의 응답 안 번호(key)는 판정에 필요 없으므로 빼고 보낸다
    sent = [{k: v for k, v in u.items() if k != "key"} for u in units]
    rendered = ctx.prompts.render(
        "judge", SCREEN_ID=sid, CODE_SCOPE=scope,
        UNITS=json.dumps(sent, ensure_ascii=False),
        CODE_FACTS=json.dumps(facts, ensure_ascii=False) if facts else NO_FACTS,
    )
    code_text = cb.text(paths)
    meta_base = {"screen_id": sid, "mode": "whole" if paths is None else "screen",
                 "files": paths, "code_tokens": code_prep.estimate_tokens(code_text),
                 "facts": len(facts or [])}

    if ctx.dry_run:
        _write_preview(ctx, f"judge_{sid}", rendered, f"코드 묶음 약 {meta_base['code_tokens']}토큰, 파일 {len(paths) if paths else len(cb.files)}개")
        return {**meta_base, "status": STATUS_DRY}

    content = [
        {"type": "text", "text": "# 코드 묶음\n" + code_text, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": rendered.user_input},
    ]
    obj, issues, meta = _call_with_retry(
        ctx, f"judge_{sid}", rendered, content, lambda o: schema.validate_judge(o, sid, unit_ids))
    meta.update(meta_base)

    if obj is None:
        meta.update(status=STATUS_FAILED, issues=[i.to_dict() for i in issues])
        write_json(ctx.path("judge", f"{sid}.meta.json"), meta)
        return meta

    results = {}
    for r in obj.get("results", []):
        if isinstance(r, dict) and r.get("unit_id") in unit_ids and r.get("status") in schema.JUDGE_STATUSES:
            r.setdefault("split_issue", None)
            results[r["unit_id"]] = r

    # 근거 줄 대조: LLM이 지어낸 근거면 판정을 확인필요로 내린다.
    # 위아래 2줄 안에 같은 코드가 있으면 줄 번호만 고치고 판정은 그대로 둔다 (evidence_fixes에 기록).
    evidence_fail = line_fixes = 0
    for r in results.values():
        fixes: list[str] = []
        problems = code_prep.verify_evidence(cb, r.get("evidence", []), fixes)
        if fixes:
            line_fixes += len(fixes)
            r["evidence_fixes"] = fixes
        r["evidence_ok"] = not problems
        if problems:
            evidence_fail += 1
            r["evidence_problems"] = problems
            if r["status"] in ("구현", "불일치"):
                r["original_status"] = r["status"]
                r["status"] = "확인필요"
                r["note"] = ((r.get("note") or "") + " [근거 불일치로 확인필요 처리]").strip()

    spacing_only = sum(1 for r in results.values() if relax_spacing(r))

    for uid in unit_ids:                    # 재시도 후에도 빠진 단위
        if uid not in results:
            results[uid] = {"unit_id": uid, "status": "확인필요", "mismatch": [], "evidence": [],
                            "note": "판정 누락 (LLM이 결과를 내지 않음)", "split_issue": None, "evidence_ok": True}

    out = {"screen_id": sid, "results": [results[u] for u in unit_ids], "extras": obj.get("extras", [])}
    write_json(ctx.path("judge", f"{sid}.json"), out)
    status = STATUS_REVIEW if schema.errors(issues) else STATUS_DONE
    meta.update(status=status, evidence_failures=evidence_fail, evidence_line_fixes=line_fixes, spacing_only=spacing_only,
                issues=[i.to_dict() for i in issues])
    write_json(ctx.path("judge", f"{sid}.meta.json"), meta)
    return meta


def relax_spacing(r: dict) -> bool:
    """불일치 이유가 문구의 띄어쓰기뿐이면 구현으로 바꾼다. 띄어쓰기는 추출 도구마다 달라서 비교하지 않기로 했다.
    바꿨으면 True. 원래 판정은 original_status에 남는다."""
    mm = r.get("mismatch") or []
    if r.get("status") != "불일치" or not mm:
        return False
    for m in mm:
        if not isinstance(m, dict) or m.get("field") != "message":
            return False
        if not m.get("spec") or pdf_utils.squash(m.get("spec")) != pdf_utils.squash(m.get("code")):
            return False
    r["original_status"] = r["status"]
    r["status"] = "구현"
    r["note"] = ((r.get("note") or "") + " [문구가 띄어쓰기만 달라 구현으로 처리]").strip()
    return True


# ---------- 전체 실행과 합치기 ----------

def run_judge(ctx: RunContext, code_root: Path, only: set[str] | None = None, mode: str | None = None,
              log=print, facts_path: Path | None = None) -> dict:
    requirements = read_json(ctx.run_dir / "requirements.json")
    facts = load_facts(facts_path)
    cb = code_prep.load_codebase(code_root)
    if not cb.files:
        raise RuntimeError(f"코드 파일을 찾지 못했습니다: {code_root}")
    units = units_by_screen(requirements)
    chosen = choose_mode(ctx.settings, cb, mode)
    write_json(ctx.path("judge", "run.json"), {
        "code_root": str(Path(code_root).resolve()), "mode": chosen,
        "code_files": len(cb.files), "code_tokens": cb.tokens(), "token_limit": ctx.settings.code_token_limit,
        "facts_file": str(Path(facts_path).resolve()) if facts_path else None,
    })
    log(f"  ③ 코드 {len(cb.files)}개 파일, 약 {cb.tokens():,}토큰 → {'전체를 넣음' if chosen == 'whole' else '화면별 묶음'}"
        + (f" · 코드 분석 결과 사용 ({facts_path})" if facts else ""))

    code_map = build_code_map(ctx, cb, requirements, units) if chosen == "screen" else None
    for sid, us in units.items():
        if only and sid not in only:
            continue
        paths = None if chosen == "whole" else bundle_for(sid, us, cb, code_map)
        meta = judge_screen(ctx, cb, sid, us, paths, facts_for(facts, sid))
        extra = f", 근거 불일치 {meta.get('evidence_failures', 0)}건" if meta.get("evidence_failures") else ""
        log(f"  ③ {sid}: {meta['status']} (단위 {len(us)}개{extra})")
    if ctx.dry_run:
        return {}
    return merge_judgments(ctx.run_dir)


def merge_judgments(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    requirements = read_json(run_dir / "requirements.json")
    by_id = {u["id"]: u for u in requirements["units"]}
    results: dict[str, dict] = {}
    extras = []
    screen_status = {}
    for m in sorted((run_dir / "judge").glob("*.meta.json")):   # 실패한 화면도 상태가 남도록 meta에서 읽는다
        if m.name != "code_map.meta.json":
            meta = read_json(m)
            screen_status[meta.get("screen_id", m.name.split(".")[0])] = meta.get("status")
    for f in sorted((run_dir / "judge").glob("*.json")):
        if f.name.endswith(".meta.json") or f.name in ("run.json", "code_map.json"):
            continue
        data = read_json(f)
        for r in data["results"]:
            uid = r["unit_id"]
            if uid in results:              # 앱 전체 단위가 여러 화면에서 판정되면 더 나쁜 쪽을 남긴다
                prev = results[uid]
                if schema.worst_status([prev["status"], r["status"]]) == prev["status"]:
                    continue
            results[uid] = {**r, "screen_id": data["screen_id"]}
        extras += [{**e, "screen_id": data["screen_id"]} for e in data.get("extras", [])]

    verdicts = {uid: r["status"] for uid, r in results.items()}
    judged_units = [by_id[u] for u in verdicts if u in by_id]
    items = schema.aggregate_items(judged_units, verdicts)
    split_issues = [{"unit_id": uid, "split_issue": r["split_issue"]} for uid, r in results.items() if r.get("split_issue")]
    merges = schema.merge_candidates(judged_units, results)

    def count(values):
        out = {}
        for v in values:
            out[v] = out.get(v, 0) + 1
        return out

    report = {
        "summary": {
            "units_judged": len(results),
            "units_not_judged": len([u for u in by_id if u not in results]),   # 실패했거나 아직 안 돌린 화면의 단위
            "by_status": count(verdicts.values()),
            "items_by_status": count(i["status"] for i in items.values()),
            "evidence_failures": sum(1 for r in results.values() if not r.get("evidence_ok", True)),
            "evidence_line_fixes": sum(len(r.get("evidence_fixes") or []) for r in results.values()),   # 줄 번호만 고친 근거
            "spacing_only": sum(1 for r in results.values()                      # 띄어쓰기만 달라 구현으로 바꾼 것
                                if r.get("original_status") == "불일치" and r.get("status") == "구현"),
            "split_issues": len(split_issues),        # 덜 쪼갠 신호
            "merge_candidates": len(merges),          # 너무 잘게 쪼갠 신호
            "extras": len(extras),
        },
        "screen_status": screen_status,
        "split_issues": split_issues,
        "merge_candidates": merges,
    }
    write_json(run_dir / "judgments.json", {"results": results, "items": items, "extras": extras})
    write_json(run_dir / "judge_report.json", report)
    return report
