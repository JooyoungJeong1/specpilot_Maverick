"""③ 정합성 판정: 코드 묶기 → 화면마다 판정 → 근거 재확인 → 항목별 집계.

코드를 넣는 방식은 크기를 재서 정한다.
- whole : 코드 전체를 화면마다 같이 넣는다 (캐시돼서 두 번째 화면부터 싸다). 놓치는 파일이 없다.
- screen: 화면마다 관련 파일만 넣는다. 관련 파일은 LLM이 파일 목록을 보고 고르고(code_map.json),
          프로그램이 단위의 문구가 들어 있는 파일과 정적 분석이 그 화면에서 닿는다고 본 파일(code_facts의 reach)을 더한다.
          사람이 code_map.json을 고쳐도 된다.

비용: 화면마다 입력 해시(프롬프트 버전 + 입력 + 코드 묶음 + 모델 설정)를 남기고, --reuse-from으로 지난 실행을 주면
해시가 같은 화면은 LLM을 부르지 않고 지난 판정을 다시 쓴다. 파일 고르기는 SPECPILOT_SELECT_MODEL로 가벼운 모델을 쓸 수 있다.
요청마다 토큰·처리시간·예상 비용은 meta에, 합계는 judge_report.json의 usage에 남는다.

근거 재확인(grounding.py): 근거 줄 대조에 더해, 근거가 그 화면의 처리 과정에서 닿는 코드인지, 조건마다 근거가 있는지,
설명에 적힌 파일·클래스·메서드가 실제로 있는지 본다. 사람이 볼 항목은 judge_report.json의 review와 judge_review.md에 모은다.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from . import code_prep, cost, grounding, pdf_utils, schema
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


def reach_of(facts: dict) -> grounding.Reach:
    """code_facts.json의 reach (근거 재확인용 도달 정보). 프롬프트에는 넣지 않는다."""
    return grounding.Reach((facts or {}).get("reach"))


def input_hash(rendered, code_text: str, settings, model: str | None = None) -> str:
    """같은 입력이면 같은 판정을 다시 쓸 수 있는지 보는 열쇠. 프롬프트 지침·입력·코드·모델 설정이 하나라도 바뀌면 달라진다."""
    h = hashlib.sha256()
    for part in (rendered.version, rendered.user_input, code_text, model or settings.model,
                 settings.thinking, settings.effort):
        h.update(str(part).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _reusable(reuse_dir: Path | None, name: str, h: str) -> tuple[Path, Path] | None:
    """지난 실행에 같은 입력 해시로 끝난 결과가 있으면 (결과 파일, meta 파일)."""
    if not reuse_dir:
        return None
    meta_p, out_p = Path(reuse_dir) / "judge" / f"{name}.meta.json", Path(reuse_dir) / "judge" / f"{name}.json"
    if not (meta_p.exists() and out_p.exists()):
        return None
    meta = read_json(meta_p)
    if meta.get("input_hash") != h or meta.get("status") != STATUS_DONE:
        return None
    return out_p, meta_p


def _reused_meta(meta: dict, reuse_dir: Path) -> dict:
    """다시 쓴 판정의 meta: 이번 실행의 비용은 0, 원래 사용량은 reused_usage에."""
    out = {k: v for k, v in meta.items() if k not in ("usage", "calls", "elapsed_sec", "cost_usd")}
    original = meta.get("reused_usage") or {"usage": meta.get("usage", {}), "elapsed_sec": meta.get("elapsed_sec"),
                                            "cost_usd": meta.get("cost_usd")}   # 재사용을 다시 재사용해도 처음 비용을 남긴다
    out.update(reused_from=meta.get("reused_from") or str(Path(reuse_dir).resolve()),
               reused_usage=original,
               usage={}, calls=[], elapsed_sec=0, cost_usd=0)
    return out


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


def build_code_map(ctx: RunContext, cb: Codebase, requirements: dict, units: dict[str, list[dict]],
                   reuse_dir: Path | None = None) -> dict:
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
    h = input_hash(rendered, "", ctx.settings, ctx.settings.select_model or None)
    hit = _reusable(reuse_dir, "code_map", h)
    if hit:                                 # 파일 목록과 화면이 같으면 지난 대응표를 그대로 쓴다
        shutil.copyfile(hit[0], path)
        write_json(ctx.run_dir / "judge" / "code_map.meta.json", _reused_meta(read_json(hit[1]), reuse_dir))
        return read_json(path)

    def validate(o):
        issues = []
        if not isinstance(o.get("mapping"), list):
            issues.append(schema.Issue("error", "code_map", "mapping이 목록이 아닙니다"))
        return issues

    obj, issues, meta = _call_with_retry(ctx, "code_select", rendered, [{"type": "text", "text": rendered.user_input}],
                                         validate, light=True)     # 파일 고르기는 분류 작업이라 가벼운 모델을 쓸 수 있다
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
    meta.update(screen_id="code_map", status=STATUS_DONE, input_hash=h)
    write_json(ctx.run_dir / "judge" / "code_map.meta.json", meta)
    return obj


def bundle_for(sid: str, units: list[dict], cb: Codebase, code_map: dict,
               reach: grounding.Reach | None = None) -> list[str]:
    """LLM이 고른 파일 + 단위 문구가 든 파일 + 정적 분석이 그 화면에서 닿는다고 본 파일."""
    files = set(code_map.get("common_files", []))
    for m in code_map.get("mapping", []):
        if m.get("screen_id") == sid:
            files |= set(m.get("files", []))
    files |= code_prep.files_mentioning(cb, _phrases(units))
    if reach is not None and sid in reach.screens:
        files |= {f for f in reach.screens[sid]["files"] if f in cb.files}
    return sorted(files)


# ---------- 화면 하나 판정 ----------

def judge_screen(ctx: RunContext, cb: Codebase, sid: str, units: list[dict], paths: list[str] | None,
                 facts: list | None = None, reach: grounding.Reach | None = None,
                 reuse_dir: Path | None = None) -> dict:
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
    reach = reach or grounding.Reach(None)
    h = input_hash(rendered, code_text, ctx.settings)
    meta_base = {"screen_id": sid, "mode": "whole" if paths is None else "screen",
                 "files": paths, "code_tokens": code_prep.estimate_tokens(code_text),
                 "facts": len(facts or []), "input_hash": h}

    if ctx.dry_run:
        _write_preview(ctx, f"judge_{sid}", rendered, f"코드 묶음 약 {meta_base['code_tokens']}토큰, 파일 {len(paths) if paths else len(cb.files)}개")
        return {**meta_base, "status": STATUS_DRY}

    hit = _reusable(reuse_dir, sid, h)
    if hit:                                 # 입력이 같으면 LLM을 부르지 않고 지난 판정을 다시 쓴다
        out = read_json(hit[0])
        results = {r["unit_id"]: r for r in out["results"]}
        counts = grounding.recheck(cb, reach, sid, units, results)      # 도달 정보가 바뀌었을 수 있어 재확인만 다시 한다
        grounding.verify_extras(cb, out.get("extras", []))
        write_json(ctx.path("judge", f"{sid}.json"), out)
        meta = _reused_meta(read_json(hit[1]), reuse_dir)
        meta.update(meta_base, status=STATUS_DONE, **counts)
        write_json(ctx.path("judge", f"{sid}.meta.json"), meta)
        return meta

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

    # 근거 재확인: 처리 과정에서 닿는 코드인가, 조건마다 근거가 있는가, 설명에 적힌 코드가 있는가
    counts = grounding.recheck(cb, reach, sid, units, results)
    extras = obj.get("extras", [])
    extras_bad = grounding.verify_extras(cb, extras)

    out = {"screen_id": sid, "results": [results[u] for u in unit_ids], "extras": extras}
    write_json(ctx.path("judge", f"{sid}.json"), out)
    status = STATUS_REVIEW if schema.errors(issues) else STATUS_DONE
    meta.update(status=status, evidence_failures=evidence_fail, evidence_line_fixes=line_fixes, spacing_only=spacing_only,
                extras_unverified=extras_bad, **counts, issues=[i.to_dict() for i in issues])
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
              log=print, facts_path: Path | None = None, reuse_from: Path | None = None) -> dict:
    requirements = read_json(ctx.run_dir / "requirements.json")
    facts = load_facts(facts_path)
    reach = reach_of(facts)
    if reuse_from is not None and not (Path(reuse_from) / "judge").is_dir():
        raise RuntimeError(f"다시 쓸 지난 판정이 없습니다: {reuse_from}/judge")
    cb = code_prep.load_codebase(code_root)
    if not cb.files:
        raise RuntimeError(f"코드 파일을 찾지 못했습니다: {code_root}")
    units = units_by_screen(requirements)
    chosen = choose_mode(ctx.settings, cb, mode)
    write_json(ctx.path("judge", "run.json"), {
        "code_root": str(Path(code_root).resolve()), "mode": chosen,
        "code_files": len(cb.files), "code_tokens": cb.tokens(), "token_limit": ctx.settings.code_token_limit,
        "facts_file": str(Path(facts_path).resolve()) if facts_path else None,
        "reach": reach.ok, "reuse_from": str(Path(reuse_from).resolve()) if reuse_from else None,
        "model": ctx.settings.model, "select_model": ctx.settings.select_model or ctx.settings.model,
    })
    log(f"  ③ 코드 {len(cb.files)}개 파일, 약 {cb.tokens():,}토큰 → {'전체를 넣음' if chosen == 'whole' else '화면별 묶음'}"
        + (f" · 코드 분석 결과 사용 ({facts_path})" if facts else ""))

    code_map = build_code_map(ctx, cb, requirements, units, reuse_from) if chosen == "screen" else None
    for sid, us in units.items():
        if only and sid not in only:
            continue
        paths = None if chosen == "whole" else bundle_for(sid, us, cb, code_map, reach)
        meta = judge_screen(ctx, cb, sid, us, paths, facts_for(facts, sid), reach, reuse_from)
        extra = f", 근거 불일치 {meta.get('evidence_failures', 0)}건" if meta.get("evidence_failures") else ""
        if meta.get("reused_from"):
            extra += ", 지난 판정 재사용"
        elif meta.get("elapsed_sec") is not None and not ctx.dry_run:
            c = meta.get("cost_usd")
            extra += f", {meta['elapsed_sec']}초" + (f", 약 ${c:.4f}" if c is not None else "")
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
    metas: dict[str, dict] = {}
    for m in sorted((run_dir / "judge").glob("*.meta.json")):   # 실패한 화면도 상태가 남도록 meta에서 읽는다
        meta = read_json(m)
        key = meta.get("screen_id", m.name.split(".")[0]) if m.name != "code_map.meta.json" else "code_map"
        metas[key] = meta
        if m.name != "code_map.meta.json":
            screen_status[key] = meta.get("status")
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
    review = review_list(results)
    usage = usage_summary(metas)

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
            "extras_unverified": sum(1 for e in extras if e.get("evidence_ok") is False),   # 근거 줄이 틀린 "설계서에 없는 구현"
            # 근거 재확인 (grounding.py)
            "needs_review": len(review),
            "unused_evidence": sum(1 for r in results.values() if any(x.startswith("미사용") for x in r.get("reach_problems") or [])),
            "reach_other_screen": sum(1 for r in results.values()
                                      if any(not x.startswith("미사용") for x in r.get("reach_problems") or [])),
            "condition_gaps": sum(1 for r in results.values() if r.get("condition_gaps")),
            "unknown_refs": sum(1 for r in results.values() if r.get("unknown_refs")),
            "usage": usage["total"],
        },
        "screen_status": screen_status,
        "split_issues": split_issues,
        "merge_candidates": merges,
        "review": review,
        "usage": usage,
    }
    write_json(run_dir / "judgments.json", {"results": results, "items": items, "extras": extras})
    write_json(run_dir / "judge_report.json", report)
    (run_dir / "judge_review.md").write_text(review_markdown(report, by_id), encoding="utf-8")
    return report


# ---------- 비용과 사람 확인 목록 ----------

USAGE_KEYS = ("input_tokens", "output_tokens", "thinking_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def usage_summary(metas: dict[str, dict]) -> dict:
    """화면(과 파일 고르기)별 토큰·처리시간·예상 비용과 합계. 재사용한 화면은 이번 실행 비용 0으로 센다."""
    def one(m: dict) -> dict:
        u = m.get("usage") or {}
        row = {k: u.get(k, 0) or 0 for k in USAGE_KEYS}
        c = m.get("cost_usd")
        if c is None and "calls" not in m and u:      # 이 기능 전의 meta: 합계 usage로 어림
            c = cost.estimate(m.get("model") or "", u)
        row.update(calls=len(m.get("calls") or []) or m.get("attempts", 0), elapsed_sec=m.get("elapsed_sec") or 0,
                   cost_usd=c, model=m.get("model"), reused=bool(m.get("reused_from")))
        return row

    by = {k: one(m) for k, m in metas.items()}
    total = {k: sum(r[k] for r in by.values()) for k in USAGE_KEYS}
    costs = [r["cost_usd"] for r in by.values() if not r["reused"]]
    total.update(calls=sum(r["calls"] for r in by.values()),
                 elapsed_sec=round(sum(r["elapsed_sec"] for r in by.values()), 2),
                 cost_usd=round(sum(c for c in costs if c is not None), 6) if None not in costs else None,
                 screens_reused=sum(1 for k, r in by.items() if r["reused"] and k != "code_map"),
                 saved_cost_usd=round(sum((m.get("reused_usage") or {}).get("cost_usd") or 0 for m in metas.values()), 6))
    read = total["cache_read_input_tokens"]
    all_in = total["input_tokens"] + total["cache_creation_input_tokens"] + read
    total["cache_read_ratio"] = round(read / all_in, 3) if all_in else 0
    return {"total": total, "by_call": by}


def review_list(results: dict[str, dict]) -> list[dict]:
    """사람이 추가로 확인할 단위: 확인필요 판정, 근거 재확인에 걸린 것."""
    out = []
    for uid, r in results.items():
        reasons = r.get("review")
        if reasons is None:                 # 이 기능 전의 판정 파일
            reasons = [] if r.get("status") != "확인필요" else ["확인필요 판정"]
        if reasons:
            out.append({"unit_id": uid, "screen_id": r.get("screen_id"), "status": r.get("status"),
                        "original_status": r.get("original_status"), "reasons": reasons})
    return out


def review_markdown(report: dict, units: dict[str, dict]) -> str:
    s, t = report["summary"], report["usage"]["total"]
    cost = f"${t['cost_usd']:.4f}" if t.get("cost_usd") is not None else "가격 모름 (SPECPILOT_PRICE)"
    lines = [
        "# ③ 사람 확인 목록", "",
        "AI 판정 가운데 코드 근거가 부족하거나 프로그램 재확인에 걸린 단위다. 판정을 그대로 믿기 전에 사람이 코드를 열어 확인한다.", "",
        f"- 판정한 단위 {s['units_judged']}개 중 확인할 단위 **{s['needs_review']}개**",
        f"- 근거 줄을 찾지 못함 {s['evidence_failures']} · 미사용 코드 근거 {s['unused_evidence']} · "
        f"다른 화면의 처리 코드 근거 {s['reach_other_screen']} · 근거 없는 조건 {s['condition_gaps']} · "
        f"설명에 적힌 코드가 없음 {s['unknown_refs']} · 근거가 틀린 '설계서에 없는 구현' {s['extras_unverified']}",
        f"- LLM 호출 {t['calls']}번, 입력 {t['input_tokens']:,} · 캐시 쓰기 {t['cache_creation_input_tokens']:,} · "
        f"캐시 읽기 {t['cache_read_input_tokens']:,} · 출력 {t['output_tokens']:,} 토큰, {t['elapsed_sec']}초, 예상 {cost}"
        + (f" (재사용 화면 {t['screens_reused']}개, 아낀 비용 약 ${t['saved_cost_usd']:.4f})" if t.get("screens_reused") else ""),
        "", "| 단위 | 화면 | 판정 | 확인할 점 | 요구사항 |", "| --- | --- | --- | --- | --- |",
    ]
    for x in report["review"]:
        u = units.get(x["unit_id"], {})
        st = x["status"] + (f" (원래 {x['original_status']})" if x.get("original_status") else "")
        req = f"{u.get('when') or ''} → {u.get('then') or ''}".strip(" →")
        cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {x['unit_id']} | {x.get('screen_id') or ''} | {st} | {cell('<br>'.join(x['reasons']))} | {cell(req)} |")
    return "\n".join(lines) + "\n"
