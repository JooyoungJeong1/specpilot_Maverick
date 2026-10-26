"""④ 시나리오 합성: 요구사항 단위를 묶어 테스트 사양서의 시나리오를 만든다.

③ 정합성 판정처럼 requirements.json만 읽는다. ③의 판정 결과와 소스 코드는 보지 않는다.
사양서의 예상결과가 코드 동작에 끌려가지 않게 하려는 것이다. 두 결과는 단위 ID로만 잇는다.

- 묶음: 화면마다 하나 (팝업은 그 팝업을 여는 화면의 묶음에 넣는다) + 앱 전체 단위 하나.
- kind "제약" 단위는 화면에서 확인할 수 없는 처리 방식이라 사양서에 넣지 않는다 (정합성 판정에만 쓴다).
- LLM은 시나리오와 단계만 쓴다. 시나리오 ID, 단계 번호, DEPTH(1)/(2)는 프로그램이 붙인다.
- 프로그램이 확인하는 것: 받은 단위가 모두 어느 단계에 들어갔는지(빠지면 그 단위만 다시 요청),
  묶음에 없는 단위 ID, 근거 단위가 없는 단계, 단위의 문구(exact.message)가 예상결과에 있는지.
  함의·issue가 있는 단위를 확인하는 단계에는 비고를 프로그램이 붙인다.

결과: scenario/<묶음>.json(.meta.json), scenarios.json(화면이 읽음), scenario_report.json, 테스트사양서.xlsx
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from . import pdf_utils, schema
from .stages import (STATUS_DONE, STATUS_DRY, STATUS_FAILED, STATUS_REVIEW, RunContext,
                     _add_usage, _call_with_retry, _write_preview, read_json, write_json)

APP = "APP"
APP_DEPTH = "앱 전체"
SKIP_KINDS = {"제약"}
SPEC_FILE = "테스트사양서.xlsx"
# ④에 보내는 단위 필드. quote·source·ref_hint는 빼서, 예상결과를 then·exact로만 쓰게 한다
# (ref_hint는 다른 화면의 값이라 이 화면의 기준이 아니다).
SENT_FIELDS = ("id", "screen_id", "origin", "reason", "kind", "given", "when", "conditions", "then", "exact", "issue")
PROFILE_FIELDS = ("flows", "login_required", "roles", "role_limited")
NOTE_MAX = 80
# 정상 짝(단위 결과의 반대를 확인하는 단계)이면 단위 문구가 예상결과에 없는 게 맞다
NEGATIONS = ("않는다", "않음", "않고", "없다", "없음")
GAP_NOTE = ("앞서 만든 시나리오에 아래 단위가 빠졌다. 이 단위들만 확인하는 시나리오를 만든다. "
            "필요하면 준비 단계를 넣고, 받은 단위 외의 ID는 쓰지 않는다.")


def _text(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _opt(v) -> str | None:
    """빈 값과 "-"는 null로 통일한다 (엑셀에서는 "-"로 보인다)."""
    s = _text(v) if not isinstance(v, (int, float)) else str(v)
    return None if s in ("", "-") else s


def _short(s: str) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= NOTE_MAX else s[:NOTE_MAX - 1] + "…"


# ---------- 묶음 ----------

def popup_parent(screen: dict, screens: dict[str, dict], flows: list) -> str | None:
    """팝업을 여는 화면. 화면 이동(flows)에서 이 팝업으로 들어오는 화면을 먼저 보고, 없으면 repeats_from을 본다."""
    sid = screen["screen_id"]
    cands = [f.get("from") for f in flows if isinstance(f, dict) and f.get("to") == sid]
    rep = screen.get("repeats_from")
    if isinstance(rep, dict):
        cands.append(rep.get("screen_id"))
    for c in cands:
        if c and c != sid and c in screens and screens[c].get("type") != "팝업":
            return c
    return None


def build_groups(requirements: dict) -> tuple[list[dict], list[dict]]:
    """(묶음 목록, 사양서에서 뺀 제약 단위). 묶음은 {"id", "screens", "units", "label"}, 화면 순서대로, 앱 전체는 끝.
    단위가 하나도 없는 묶음은 뺀다."""
    profile = requirements.get("app_profile") or {}
    screens = [s for s in profile.get("screens", []) if isinstance(s, dict) and s.get("screen_id")]
    by_sid = {s["screen_id"]: s for s in screens}
    flows = profile.get("flows") or []
    units = [u for u in requirements.get("units", []) if isinstance(u, dict) and u.get("id")]
    excluded = [u for u in units if u.get("kind") in SKIP_KINDS]

    owner = {}
    for s in screens:
        parent = popup_parent(s, by_sid, flows) if s.get("type") == "팝업" else None
        owner[s["screen_id"]] = parent or s["screen_id"]
    groups: dict[str, dict] = {}
    for s in screens:
        g = groups.setdefault(owner[s["screen_id"]], {"id": owner[s["screen_id"]], "screens": [], "units": []})
        g["screens"].append(s["screen_id"])
    app = {"id": APP, "screens": [], "units": []}
    for u in units:
        if u.get("kind") in SKIP_KINDS:
            continue
        sid = u.get("screen_id")
        if sid == APP:
            app["units"].append(u)
        elif sid in owner:
            groups[owner[sid]]["units"].append(u)
        else:                                   # 앱 프로필에 없는 화면 (보통은 없음)
            groups.setdefault(sid, {"id": sid, "screens": [sid], "units": []})["units"].append(u)

    out = []
    for g in list(groups.values()) + [app]:
        if not g["units"]:
            continue
        if g["id"] in g["screens"]:            # 묶음의 주 화면을 맨 앞에
            g["screens"] = [g["id"]] + [s for s in g["screens"] if s != g["id"]]
        g["label"] = _label(g, by_sid)
        out.append(g)
    return out, excluded


def _label(group: dict, screens: dict[str, dict]) -> str:
    if group["id"] == APP:
        return "APP 앱 전체 (여러 화면에 걸친 단위)"
    name = lambda sid: f"{sid} {(screens.get(sid) or {}).get('name') or ''}".strip()
    popups = [name(s) for s in group["screens"][1:]]
    return name(group["id"]) + (f" (팝업 {', '.join(popups)} 포함)" if popups else "")


def profile_brief(profile: dict) -> dict:
    """④에 넣는 앱 프로필: 화면 목록(ID, 이름, Depth, 종류)과 화면 이동, 로그인 필요 여부, 역할."""
    out = {"screens": [{k: s.get(k) for k in ("screen_id", "name", "depth", "type")}
                       for s in profile.get("screens", []) if isinstance(s, dict)]}
    for k in PROFILE_FIELDS:
        if k in profile:
            out[k] = profile[k]
    return out


# ---------- 검사 ----------

def normalize(obj) -> None:
    """검사 전에 모양만 맞춘다: unit_ids가 문자열 하나면 목록으로, setup은 참/거짓으로."""
    if not isinstance(obj, dict) or not isinstance(obj.get("scenarios"), list):
        return
    for sc in obj["scenarios"]:
        if not isinstance(sc, dict) or not isinstance(sc.get("steps"), list):
            continue
        for st in sc["steps"]:
            if not isinstance(st, dict):
                continue
            ids = st.get("unit_ids")
            if isinstance(ids, str):
                st["unit_ids"] = [x.strip() for x in ids.split(",") if x.strip()]
            elif ids is None:
                st["unit_ids"] = []
            st["setup"] = bool(st.get("setup"))


def validate_scenarios(obj, unit_ids: list[str]) -> list[schema.Issue]:
    """형식과 단위 ID를 검사한다. 단위가 빠졌는지(커버리지)는 여기서 보지 않고 따로 다시 요청한다."""
    issues: list[schema.Issue] = []
    err = lambda where, msg: issues.append(schema.Issue("error", where, msg))
    if not isinstance(obj, dict) or not isinstance(obj.get("scenarios"), list):
        return [schema.Issue("error", "scenarios", '"scenarios" 목록이 없습니다')]
    if unit_ids and not obj["scenarios"]:
        return [schema.Issue("error", "scenarios", "시나리오가 하나도 없습니다")]
    known = set(unit_ids)
    for i, sc in enumerate(obj["scenarios"], 1):
        where = f"시나리오 {i}"
        if not isinstance(sc, dict) or not isinstance(sc.get("steps"), list) or not sc["steps"]:
            err(where, "steps 목록이 없거나 비어 있습니다")
            continue
        for j, st in enumerate(sc["steps"], 1):
            w = f"{where} 단계 {j}"
            if not isinstance(st, dict):
                err(w, "단계가 객체가 아닙니다")
                continue
            for k in ("action", "expected"):
                if not _text(st.get(k)):
                    err(w, f"{k}가 비어 있습니다")
            ids = st.get("unit_ids")
            if not isinstance(ids, list):
                err(w, "unit_ids는 목록이어야 합니다")
                continue
            unknown = [str(x) for x in ids if x not in known]
            if unknown:
                err(w, f"이 묶음에 없는 단위 ID: {', '.join(unknown)}. 받은 단위의 ID만 쓴다")
    return issues


def covered_ids(scenarios: list[dict]) -> set[str]:
    return {x for sc in scenarios for st in sc.get("steps", []) if isinstance(st, dict)
            for x in (st.get("unit_ids") or [])}


def _drop_unknown(scenarios: list[dict], known: set[str]) -> int:
    """재시도 뒤에도 남은, 묶음에 없는 단위 ID를 뺀다. 뺀 개수를 돌려준다."""
    n = 0
    for sc in scenarios:
        for st in sc.get("steps", []):
            if isinstance(st, dict) and isinstance(st.get("unit_ids"), list):
                keep = [x for x in st["unit_ids"] if x in known]
                n += len(st["unit_ids"]) - len(keep)
                st["unit_ids"] = keep
    return n


def post_checks(scenarios: list[dict], by_id: dict[str, dict]) -> list[schema.Issue]:
    """마무리한 시나리오의 경고: 근거 단위 없는 단계(지어낸 단계일 수 있음), 단위 문구가 예상결과에 없음."""
    out: list[schema.Issue] = []
    for sc in scenarios:
        for st in sc["steps"]:
            where = f"{sc['scenario_id']} 단계 {st['no']}"
            if not st["unit_ids"] and not st["setup"]:
                out.append(schema.Issue("warning", where, "근거 단위가 없는 단계입니다 (준비 단계가 아니면 지어낸 단계일 수 있음)"))
            expected = pdf_utils.squash(st["expected"])
            for uid in st["unit_ids"]:
                msg = ((by_id.get(uid) or {}).get("exact") or {}).get("message")
                if not msg or pdf_utils.squash(msg) in expected:
                    continue
                if any(n in st["expected"] for n in NEGATIONS) or "정상" in (st.get("note") or ""):
                    continue
                out.append(schema.Issue("warning", where, f'{uid}의 문구가 예상결과에 없습니다: "{msg}"'))
    return out


# ---------- 마무리 (프로그램이 붙이는 것) ----------

def _notes(note: str | None, units: list[dict]) -> str | None:
    """함의 단위와 issue가 있는 단위를 확인하는 단계에는 비고를 붙인다 (LLM이 빠뜨려도 같은 기준으로)."""
    parts = [note] if note else []
    text = note or ""
    implied = [u for u in units if u.get("origin") == "함의"]
    if implied and "함의" not in text:
        parts.append("함의: " + _short(implied[0].get("reason") or implied[0].get("then") or ""))
    flagged = [u for u in units if _text(u.get("issue"))]
    if flagged and "확인 필요" not in text:
        parts.append("확인 필요: " + _short(flagged[0]["issue"]))
    return " / ".join(p for p in parts if p) or None


def _depths(sc: dict, group: dict, by_id: dict[str, dict], screens: dict[str, dict]) -> tuple[str, str]:
    """DEPTH(1)은 묶음 주 화면의 Depth, DEPTH(2)는 이 시나리오가 가장 많이 확인하는 화면의 이름.
    앱 전체 묶음은 DEPTH(1) "앱 전체", DEPTH(2)는 LLM이 적은 기능 이름(category)."""
    if group["id"] == APP:
        return APP_DEPTH, _text(sc.get("category")) or APP_DEPTH
    main = group["id"]
    count = Counter(by_id[x]["screen_id"] for st in sc.get("steps", []) if isinstance(st, dict)
                    for x in (st.get("unit_ids") or []) if x in by_id)
    sid = max(group["screens"], key=lambda s: (count.get(s, 0), s == main)) if count else main
    depth1 = _text((screens.get(main) or {}).get("depth")) or _text((screens.get(sid) or {}).get("depth")) or main
    return depth1, _text((screens.get(sid) or {}).get("name")) or sid


def finish(scenarios: list[dict], group: dict, by_id: dict[str, dict], screens: dict[str, dict]) -> list[dict]:
    """시나리오 ID(TC-<묶음>-NN), 단계 번호, DEPTH를 붙이고 비고를 채운다. 화면(frontend)이 읽는 모양이다."""
    out = []
    for n, sc in enumerate(scenarios, 1):
        steps = []
        for st in sc.get("steps", []):
            if not isinstance(st, dict):
                continue
            ids = [x for x in (st.get("unit_ids") or []) if x in by_id]
            steps.append({
                "no": len(steps) + 1,
                "action": _text(st.get("action")),
                "expected": _text(st.get("expected")),
                "account": _opt(st.get("account")),
                "input": _opt(st.get("input")),
                "data_source": _opt(st.get("data_source")),
                "note": _notes(_opt(st.get("note")), [by_id[x] for x in ids]),
                "unit_ids": ids,
                "setup": bool(st.get("setup")) and not ids,
            })
        if not steps:
            continue
        depth1, depth2 = _depths(sc, group, by_id, screens)
        out.append({"scenario_id": f"TC-{group['id']}-{len(out) + 1:02d}", "title": _text(sc.get("title")) or depth2,
                    "depth1": depth1, "depth2": depth2, "steps": steps})
    return out


# ---------- 묶음 하나 ----------

def _compose(ctx: RunContext, name: str, label: str, units: list[dict], profile: dict, note: str = "없음"):
    sent = [{k: u.get(k) for k in SENT_FIELDS} for u in units]
    rendered = ctx.prompts.render("scenario", GROUP=label, UNITS=json.dumps(sent, ensure_ascii=False),
                                  APP_PROFILE=json.dumps(profile, ensure_ascii=False), NOTE=note)
    if ctx.dry_run:
        _write_preview(ctx, name, rendered, "(첨부 없음. ④는 requirements.json만 쓴다)")
        return None, [], {}
    ids = [u["id"] for u in units]
    content = [{"type": "text", "text": rendered.user_input}]
    return _call_with_retry(ctx, name, rendered, content, lambda o: validate_scenarios(o, ids), prepare=normalize)


def run_group(ctx: RunContext, group: dict, profile: dict, by_id: dict[str, dict], screens: dict[str, dict]) -> dict:
    gid = group["id"]
    ids = [u["id"] for u in group["units"]]
    base = {"group_id": gid, "screens": group["screens"], "units": len(ids)}
    obj, issues, meta = _compose(ctx, f"scenario_{gid}", group["label"], group["units"], profile)
    if ctx.dry_run:
        return {**base, "status": STATUS_DRY}
    meta.update(base)
    if obj is None:
        meta.update(status=STATUS_FAILED, issues=[i.to_dict() for i in issues])
        write_json(ctx.path("scenario", f"{gid}.meta.json"), meta)
        return meta

    scenarios = [sc for sc in obj.get("scenarios", []) if isinstance(sc, dict)]
    dropped = _drop_unknown(scenarios, set(ids))
    missing = [u for u in group["units"] if u["id"] not in covered_ids(scenarios)]
    gap = None
    if missing:                                  # 빠진 단위만 다시 요청한다
        gobj, gissues, gmeta = _compose(ctx, f"scenario_{gid}_gap", group["label"], missing, profile, GAP_NOTE)
        _add_usage(meta["usage"], gmeta.get("usage", {}))
        gap = {"units": [u["id"] for u in missing], "attempts": gmeta.get("attempts"),
               "issues": [i.to_dict() for i in gissues]}
        if gobj is not None:
            extra = [sc for sc in gobj.get("scenarios", []) if isinstance(sc, dict)]
            dropped += _drop_unknown(extra, {u["id"] for u in missing})
            scenarios += extra
        issues = issues + gissues

    done = finish(scenarios, group, by_id, screens)
    covered = covered_ids(done)
    uncovered = [i for i in ids if i not in covered]
    warnings = post_checks(done, by_id) + [i for i in issues if i.level == "warning"]
    if dropped:
        warnings.append(schema.Issue("warning", gid, f"묶음에 없는 단위 ID {dropped}개를 뺐습니다"))
    write_json(ctx.path("scenario", f"{gid}.json"), {
        "group_id": gid, "screens": group["screens"], "scenarios": done, "uncovered": uncovered,
        "warnings": [w.to_dict() for w in warnings],
    })
    status = STATUS_REVIEW if uncovered or schema.errors(issues) else STATUS_DONE
    meta.update(status=status, scenarios=len(done), steps=sum(len(s["steps"]) for s in done),
                uncovered=uncovered, gap=gap, warnings=len(warnings), issues=[i.to_dict() for i in issues])
    write_json(ctx.path("scenario", f"{gid}.meta.json"), meta)
    return meta


# ---------- 전체 실행과 합치기 ----------

def _screens(requirements: dict) -> dict[str, dict]:
    return {s["screen_id"]: s for s in (requirements.get("app_profile") or {}).get("screens", [])
            if isinstance(s, dict) and s.get("screen_id")}


def run_scenario(ctx: RunContext, only: set[str] | None = None, log=print, project: str | None = None) -> dict:
    requirements = read_json(ctx.run_dir / "requirements.json")
    groups, excluded = build_groups(requirements)
    profile = profile_brief(requirements.get("app_profile") or {})
    by_id = {u["id"]: u for u in requirements.get("units", []) if isinstance(u, dict) and u.get("id")}
    screens = _screens(requirements)
    names = {g["id"] for g in groups} | {s for g in groups for s in g["screens"]}
    unknown = (only or set()) - names
    if unknown:
        log(f"  [경고] 묶음이나 화면에 없는 ID: {', '.join(sorted(unknown))}")
    picked = [g for g in groups if not only or g["id"] in only or set(g["screens"]) & only]
    log(f"  ④ 묶음 {len(picked)}개, 단위 {sum(len(g['units']) for g in picked)}개 "
        f"(제약 단위 {len(excluded)}개는 사양서에 넣지 않음)")
    for g in picked:
        meta = run_group(ctx, g, profile, by_id, screens)
        extra = ""
        if meta.get("uncovered"):
            extra = f", 사양서에 못 넣은 단위 {len(meta['uncovered'])}개"
        elif meta.get("gap"):
            extra = f", 빠진 단위 {len(meta['gap']['units'])}개 다시 요청"
        detail = f" · 시나리오 {meta['scenarios']}개 단계 {meta['steps']}개" if "scenarios" in meta else ""
        log(f"  ④ {g['id']}: {meta['status']} (단위 {len(g['units'])}개{detail}{extra})")
    if ctx.dry_run:
        return {}
    return merge_scenarios(ctx.run_dir, project=project, log=log)


def default_project(run_dir: Path) -> str:
    """사양서 머리글의 프로젝트명. 실행 때 쓴 기획서 파일 이름, 없으면 실행 ID."""
    p = Path(run_dir) / "run.json"
    if p.exists():
        src = (read_json(p) or {}).get("source_pdf")
        if src:
            return Path(str(src).replace("\\", "/")).stem
    return Path(run_dir).name


def merge_scenarios(run_dir: Path, project: str | None = None, log=print) -> dict:
    """묶음별 결과를 합쳐 scenarios.json, scenario_report.json, 테스트사양서.xlsx를 쓴다. LLM을 부르지 않는다."""
    run_dir = Path(run_dir)
    requirements = read_json(run_dir / "requirements.json")
    groups, excluded = build_groups(requirements)
    folder = run_dir / "scenario"
    files = {f.name[:-5]: f for f in folder.glob("*.json") if not f.name.endswith(".meta.json")} if folder.exists() else {}
    order = [g["id"] for g in groups] + sorted(set(files) - {g["id"] for g in groups})

    scenarios, uncovered, warnings, status = [], [], [], {}
    for gid in order:
        meta_path = folder / f"{gid}.meta.json"
        if meta_path.exists():
            status[gid] = read_json(meta_path).get("status")
        if gid in files:
            data = read_json(files[gid])
            scenarios += data.get("scenarios", [])
            uncovered += data.get("uncovered", [])
            warnings += data.get("warnings", [])

    by_id = {u["id"]: u for u in requirements.get("units", []) if isinstance(u, dict) and u.get("id")}
    target = [u["id"] for g in groups for u in g["units"]]
    covered = covered_ids(scenarios)
    not_run = [i for i in target if i not in covered and i not in uncovered]
    excluded_ids = [u["id"] for u in excluded]
    write_json(run_dir / "scenarios.json", {
        "meta": {"merged_at": datetime.now().isoformat(timespec="seconds"), "groups": status},
        "scenarios": scenarios, "uncovered": uncovered, "not_run": not_run, "excluded": excluded_ids,
    })

    def brief(uid):
        u = by_id.get(uid) or {}
        return {"id": uid, "screen_id": u.get("screen_id"), "then": u.get("then")}

    report = {
        "summary": {
            "groups": len(groups),
            "groups_done": sum(1 for s in status.values() if s == STATUS_DONE),
            "scenarios": len(scenarios),
            "steps": sum(len(s.get("steps", [])) for s in scenarios),
            "units_target": len(target),
            "units_covered": len([i for i in target if i in covered]),
            "units_uncovered": len(uncovered),     # 다시 요청해도 어느 단계에도 들어가지 않은 단위
            "units_not_run": len(not_run),         # 아직 ④를 돌리지 않았거나 실패한 묶음의 단위
            "units_excluded": len(excluded_ids),   # 제약 단위 (정합성 판정에만 씀)
            "warnings": len(warnings),
        },
        "group_status": status,
        "uncovered": [brief(i) for i in uncovered],
        "not_run": [brief(i) for i in not_run],
        "warnings": warnings,
        "spec_file": None,
    }
    try:
        from .excel import write_spec
    except ImportError as e:                     # openpyxl이 없으면 엑셀만 건너뛴다
        log(f"  [경고] 엑셀을 만들지 못했습니다 ({e}). pip install -r requirements.txt 후 scenario --excel-only")
    else:
        path = run_dir / SPEC_FILE
        write_spec(path, scenarios, requirements, project=project or default_project(run_dir), written=date.today(),
                   uncovered=set(uncovered) | set(not_run), excluded=set(excluded_ids))
        report["spec_file"] = path.name
    write_json(run_dir / "scenario_report.json", report)
    return report
