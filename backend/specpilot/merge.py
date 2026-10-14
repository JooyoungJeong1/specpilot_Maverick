"""app_profile.json + screens/*.json → requirements.json, validation_report.json

LLM을 쓰지 않는다. 이어 붙이고 검사하는 일이라 프로그램이 더 정확하고 비용도 들지 않는다.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from . import schema
from .stages import STATUS_DONE, STATUS_REJECTED, read_json, write_json


def _optional(path: Path):
    return read_json(path) if path.exists() else None


def merge(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    profile = read_json(run_dir / "app_profile.json")
    issues: list[schema.Issue] = []

    units = list(profile.get("units", []))
    questions = list(profile.get("questions", []))
    skipped: dict[str, list] = {}
    rejected_screens: dict[str, str] = {}
    rejected_units: dict[str, dict] = {}
    if (profile.get("rejected") or {}).get("units") or (profile.get("rejected") or {}).get("questions"):
        rejected_units["APP"] = profile["rejected"]
        issues.append(schema.Issue("warning", "APP", "① 검사를 통과하지 못해 뺀 앱 전체 단위·질문이 있습니다 "
                                                     "(app_profile.json의 rejected)"))
    screen_status: dict[str, dict] = {}

    for s in profile.get("screens", []):
        sid = s["screen_id"]
        data_path = run_dir / "screens" / f"{sid}.json"
        meta_path = run_dir / "screens" / f"{sid}.meta.json"
        meta = read_json(meta_path) if meta_path.exists() else {}
        status = meta.get("status") or ("미실행" if not data_path.exists() else "알수없음")

        if status == STATUS_REJECTED:
            reason = meta.get("reject_reason") or "이유 없음"
            rejected_screens[sid] = reason
            screen_status[sid] = {"status": status, "units": 0, "reject_reason": reason,
                                  "rejected_by": meta.get("rejected_by", "②")}
            issues.append(schema.Issue("warning", sid, f"반려된 화면입니다 (단위에서 뺌): {reason}"))
            continue
        if not data_path.exists():
            issues.append(schema.Issue("error", sid, f"화면 결과가 없습니다 (상태: {status})"))
            screen_status[sid] = {"status": status, "units": 0}
            continue

        data = read_json(data_path)
        units += data.get("units", [])
        questions += data.get("questions", [])
        skipped[sid] = data.get("skipped", [])
        rej = data.get("rejected") or {}
        if rej.get("units") or rej.get("questions"):
            rejected_units[sid] = rej
            issues.append(schema.Issue("warning", sid, f"검사를 통과하지 못해 뺀 단위 {len(rej.get('units', []))}개, "
                                                       f"질문 {len(rej.get('questions', []))}개 (screens/{sid}.json의 rejected)"))
        screen_status[sid] = {
            "status": status,
            "units": len(data.get("units", [])),
            "questions": len(data.get("questions", [])),
            "attempts": meta.get("attempts"),
            "prompt_version": meta.get("prompt_version"),
        }
        if status != STATUS_DONE:
            issues.append(schema.Issue("warning", sid, f"화면 상태가 '{status}'입니다. screens/{sid}.meta.json의 issues를 확인하세요"))

    # 전체 기준으로 한 번 더: 중복 id, 없는 단위를 가리키는 질문
    issues += schema.duplicate_ids(units, "단위")
    issues += schema.duplicate_ids(questions, "질문")
    unit_ids = {u.get("id") for u in units if isinstance(u, dict)}
    for q in questions:
        for rid in q.get("related_units", []) if isinstance(q, dict) else []:
            if rid not in unit_ids:
                issues.append(schema.Issue("warning", str(q.get("id")), f"related_units의 {rid}가 단위 목록에 없습니다"))
    # 질문은 우선순위 상을 먼저 (같은 우선순위 안에서는 원래 순서)
    questions = sorted(questions, key=lambda q: 0 if isinstance(q, dict) and q.get("priority") == "상" else 1)

    pre = _optional(run_dir / "preflight.json")
    gate = _optional(run_dir / "gate.json")
    profile_only = {k: v for k, v in profile.items() if k not in ("units", "questions", "rejected")}
    requirements = {
        "meta": {"merged_at": datetime.now().isoformat(timespec="seconds"), "run_dir": run_dir.name},
        "app_profile": profile_only,
        "units": units,
        "questions": questions,
        "skipped": skipped,
        "screen_status": screen_status,
        "rejected_screens": rejected_screens,
        "rejected_units": rejected_units,
    }
    report = {
        "summary": {
            "screens": len(screen_status),
            "screens_done": sum(1 for v in screen_status.values() if v["status"] == STATUS_DONE),
            "screens_rejected": len(rejected_screens),
            "units": len(units),
            "units_rejected": sum(len(r.get("units", [])) for r in rejected_units.values()),
            "questions": len(questions),
            "questions_by_priority": dict(Counter(q.get("priority") for q in questions if isinstance(q, dict))),
            "by_kind": dict(Counter(u.get("kind") for u in units if isinstance(u, dict))),
            "by_origin": dict(Counter(u.get("origin") for u in units if isinstance(u, dict))),
            "errors": len(schema.errors(issues)),
        },
        "input": {
            "preflight": None if pre is None else {"verdict": pre.get("verdict"), "reasons": pre.get("reasons"),
                                                   "warnings": pre.get("warnings"), "extractor": pre.get("extractor")},
            "gate": None if gate is None else {"verdict": gate.get("verdict"), "reasons": gate.get("reasons"),
                                               "warnings": gate.get("warnings"),
                                               "screen_warnings": {k: v["warnings"] for k, v in gate.get("screens", {}).items()
                                                                   if v.get("warnings")}},
        },
        "screen_status": screen_status,
        "issues": [i.to_dict() for i in issues],
    }
    write_json(run_dir / "requirements.json", requirements)
    write_json(run_dir / "validation_report.json", report)
    return report
