"""명령줄 실행.

  python -m specpilot check --pdf ../../specpilot-inputs/plan.pdf                입력 점검만 (API 호출 없음, 무료)
  python -m specpilot run --pdf ../../specpilot-inputs/plan.pdf                  전체 실행 (입력 점검 → ① → 게이트 → ② 전 화면 → 합치기)
  python -m specpilot run --pdf ../../specpilot-inputs/plan.pdf --dry-run        API 호출 없이 프롬프트만 파일로 확인
  python -m specpilot screen --run output/<실행ID> --screen NOTICE-001   화면 하나만 다시 실행 후 다시 합치기
  python -m specpilot screen --run output/<실행ID> --screen MYPAGE-001 --pdf 고친기획서.pdf   기획서를 고친 뒤 그 화면만
  python -m specpilot merge --run output/<실행ID>           합치기·검사만 다시
  python -m specpilot judge --run output/<실행ID> --code ../../specpilot-inputs/sample-code   ③ 정합성 판정
  python -m specpilot scenario --run output/<실행ID>          ④ 시나리오 합성 → 테스트사양서.xlsx
  python -m specpilot scenario --run output/<실행ID> --excel-only   엑셀만 다시 (API 호출 없음)
  python -m specpilot serve                                   시연용 서버 (웹에서 기획서·코드를 올려 끝까지 실행)
  python -m specpilot trace --run output/<실행ID> --unit REQ-LOGIN-001-07   거꾸로 따라가기
  python -m specpilot score --run output/<실행ID> --key ../../specpilot-private/answer_key.json   ③ 채점 (조장용)
  python -m specpilot validate --screen-file a.json --screen-id NOTICE-001   JSON 파일 하나 검사
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import pdf_utils, preflight, schema
from .config import Settings
from .merge import merge
from .prompts import PromptSet
from .stages import (STATUS_DONE, STATUS_REJECTED, RunContext, StageFailed, mark_rejected, read_json,
                     run_app_profile, run_screen, write_json)

EXIT_REJECTED = 3   # 입력 점검·게이트에서 기획서를 반려함


def _make_llm(settings: Settings, dry_run: bool):
    if dry_run:
        return None
    from .llm import AnthropicLLM
    return AnthropicLLM(settings.model, settings.thinking, settings.effort)


def _print_report(report: dict, run_dir: Path) -> None:
    s = report["summary"]
    print(f"\n[결과] {run_dir}")
    print(f"  화면 {s['screens_done']}/{s['screens']} 완료 (반려 {s.get('screens_rejected', 0)}) · 단위 {s['units']}개 · "
          f"질문 {s['questions']}개 {s.get('questions_by_priority', {})} · 오류 {s['errors']}건")
    for sid, st in report["screen_status"].items():
        mark = "  " if st["status"] == STATUS_DONE else ("× " if st["status"] == STATUS_REJECTED else "! ")
        extra = f"  {st['reject_reason']}" if st.get("reject_reason") else ""
        print(f"  {mark}{sid:<14} {st['status']:<6} 단위 {st.get('units', 0)}{extra}")
    print("  자세한 내용: validation_report.json")


def _do_preflight(ctx: RunContext, settings: Settings) -> dict:
    """입력 점검 (프로그램만, 무료). 결과는 preflight.json."""
    report = preflight.run_preflight(ctx.pdf_path, settings.marker_match_min, settings.reject_ratio)
    write_json(ctx.run_dir / "preflight.json", report)
    ctx._preflight = report
    print(preflight.format_preflight(report))
    return report


def _do_gate(ctx: RunContext, profile: dict, settings: Settings) -> dict:
    """게이트 판정 (① 결과로 쪽을 화면에 묶어 판단). 결과는 gate.json."""
    gate = preflight.gate_screens(ctx.preflight, profile, settings.marker_match_min, settings.reject_ratio)
    write_json(ctx.run_dir / "gate.json", gate)
    print(preflight.format_gate(gate))
    return gate


def _run_screens(ctx: RunContext, profile: dict, only: set[str] | None, workers: int,
                 gate: dict | None = None, force: bool = False) -> None:
    screens = [s for s in profile["screens"] if not only or s["screen_id"] in only]
    unknown = (only or set()) - {s["screen_id"] for s in profile["screens"]}
    if unknown:
        print(f"[경고] 앱 프로필에 없는 화면 ID: {', '.join(sorted(unknown))}", file=sys.stderr)

    todo = []
    for s in screens:
        verdict = ((gate or {}).get("screens", {}).get(s["screen_id"]) or {})
        if verdict.get("verdict") == preflight.REJECT and not force:
            mark_rejected(ctx, s, verdict.get("reasons", []))
            print(f"  ② {s['screen_id']}: 반려 (게이트) — {'; '.join(verdict.get('reasons', []))}")
        else:
            todo.append(s)

    def one(screen):
        meta = run_screen(ctx, screen, profile)
        extra = f" — {meta['reject_reason']}" if meta.get("reject_reason") else ""
        print(f"  ② {screen['screen_id']}: {meta['status']} (시도 {meta.get('attempts', '-')}){extra}")
        return meta

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo))
    else:
        for s in todo:
            one(s)


def cmd_run(args) -> int:
    settings = Settings()
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"PDF가 없습니다: {pdf}", file=sys.stderr)
        return 2
    run_id = args.name or datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = settings.output_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    pdf_copy = pdf_utils.copy_input(pdf, run_dir)
    write_json(run_dir / "run.json", {
        "run_id": run_id, "source_pdf": str(pdf), "model": settings.model,
        "dry_run": args.dry_run, "send_full_pdf": settings.send_full_pdf,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    })
    # 입력 점검은 API를 쓰지 않으므로, API 클라이언트는 점검을 통과한 뒤에 만든다
    ctx = RunContext(run_dir, pdf_copy, settings, PromptSet(settings.prompts_dir), None)
    print(f"[실행] {run_dir}  모델 {settings.model}{'  (dry-run)' if args.dry_run else ''}")

    report = _do_preflight(ctx, settings)
    if report["verdict"] == preflight.REJECT and not args.force:
        print("  기획서를 반려합니다. 고친 뒤 다시 실행하세요 (점검 결과를 무시하고 돌리려면 --force)", file=sys.stderr)
        return EXIT_REJECTED
    ctx.llm = _make_llm(settings, args.dry_run)

    if args.app_profile:
        profile = read_json(Path(args.app_profile))
        schema.normalize_app_profile(profile)
        write_json(run_dir / "app_profile.json", profile)
        print("  ① 기존 앱 프로필 사용")
    else:
        try:
            profile = run_app_profile(ctx)
            print(f"  ① 앱 프로필: 화면 {len(profile['screens'])}개")
        except StageFailed as e:
            if args.dry_run:
                print(f"  ① 프롬프트 미리보기 저장. {e}")
                return 0
            print(f"  ① {e}", file=sys.stderr)
            return 1

    gate = _do_gate(ctx, profile, settings)
    if gate["verdict"] == preflight.REJECT and not args.force:
        print("  ②를 돌리지 않습니다. 기획서를 고친 뒤 다시 실행하세요 (무시하고 돌리려면 --force)", file=sys.stderr)
        return EXIT_REJECTED

    only = set(args.screens.split(",")) if args.screens else None
    _run_screens(ctx, profile, only, args.workers, gate, args.force)
    if args.dry_run:
        print(f"  프롬프트 미리보기: {run_dir / 'prompts_preview'}")
        return 0
    _print_report(merge(run_dir), run_dir)
    return 0


def cmd_screen(args) -> int:
    settings = Settings()
    run_dir = Path(args.run)
    profile = read_json(run_dir / "app_profile.json")
    pdf = run_dir / "input.pdf"
    if args.pdf:
        new = Path(args.pdf)
        if not new.exists():
            print(f"PDF가 없습니다: {new}", file=sys.stderr)
            return 2
        before, after = pdf_utils.page_count(pdf), pdf_utils.page_count(new)
        if before != after:
            print(f"쪽 수가 달라졌습니다 ({before} → {after}). ①의 화면↔쪽 대응이 맞지 않으니 run으로 처음부터 실행하세요",
                  file=sys.stderr)
            return 2
        pdf_utils.copy_input(new, run_dir)
        run_info = read_json(run_dir / "run.json") if (run_dir / "run.json").exists() else {}
        run_info.setdefault("replaced_pdf", []).append({"path": str(new), "screens": args.screen,
                                                        "at": datetime.now().isoformat(timespec="seconds")})
        write_json(run_dir / "run.json", run_info)
        print(f"  기획서를 바꿨습니다: {new}")
    ctx = RunContext(run_dir, pdf, settings, PromptSet(settings.prompts_dir), _make_llm(settings, args.dry_run))
    if args.pdf or ctx.preflight is None:
        report = _do_preflight(ctx, settings)
        if report["verdict"] == preflight.REJECT and not args.force:
            print("  기획서를 반려합니다. 고친 뒤 다시 실행하세요 (무시하고 돌리려면 --force)", file=sys.stderr)
            return EXIT_REJECTED
    gate = _do_gate(ctx, profile, settings)
    _run_screens(ctx, profile, set(args.screen.split(",")), workers=1, gate=gate, force=args.force)
    if not args.dry_run:
        _print_report(merge(run_dir), run_dir)
    return 0


def cmd_check(args) -> int:
    """입력 점검만 한다. API를 부르지 않고 파일도 만들지 않는다."""
    settings = Settings()
    pdf = Path(args.pdf)
    if not pdf.exists():
        print(f"PDF가 없습니다: {pdf}", file=sys.stderr)
        return 2
    report = preflight.run_preflight(pdf, settings.marker_match_min, settings.reject_ratio)
    print(preflight.format_preflight(report))
    verdict = report["verdict"]
    if args.app_profile:
        profile = read_json(Path(args.app_profile))
        schema.normalize_app_profile(profile)
        gate = preflight.gate_screens(report, profile, settings.marker_match_min, settings.reject_ratio)
        print(preflight.format_gate(gate))
        if gate["verdict"] == preflight.REJECT:
            verdict = preflight.REJECT
    return EXIT_REJECTED if verdict == preflight.REJECT else 0


def cmd_merge(args) -> int:
    run_dir = Path(args.run)
    _print_report(merge(run_dir), run_dir)
    return 0


def cmd_judge(args) -> int:
    from .judge import run_judge

    settings = Settings()
    run_dir = Path(args.run)
    if not (run_dir / "requirements.json").exists():
        print("requirements.json이 없습니다. run이나 merge를 먼저 하세요", file=sys.stderr)
        return 2
    ctx = RunContext(run_dir, run_dir / "input.pdf", settings, PromptSet(settings.prompts_dir),
                     _make_llm(settings, args.dry_run))
    only = set(args.screens.split(",")) if args.screens else None
    try:
        report = run_judge(ctx, Path(args.code), only, args.mode,
                           facts_path=Path(args.facts) if args.facts else None)
    except RuntimeError as e:
        print(f"  ③ {e}", file=sys.stderr)
        return 1
    if report:
        s = report["summary"]
        print(f"\n[③ 결과] 단위 {s['units_judged']}개 판정 (판정 안 된 단위 {s['units_not_judged']}개): {s['by_status']}")
        print(f"  기획서 항목별: {s['items_by_status']}")
        print(f"  근거 불일치 {s['evidence_failures']} · 띄어쓰기만 달라 구현 처리 {s.get('spacing_only', 0)} · 판정 갈림(덜 쪼갠 신호) {s['split_issues']} · "
              f"합칠 후보(너무 쪼갠 신호) {s['merge_candidates']} · 기획서에 없는 구현 {s['extras']}")
        print("  자세한 내용: judge_report.json, judgments.json")
    return 0


def cmd_scenario(args) -> int:
    from .scenario import merge_scenarios, run_scenario

    settings = Settings()
    run_dir = Path(args.run)
    if not (run_dir / "requirements.json").exists():
        print("requirements.json이 없습니다. run이나 merge를 먼저 하세요", file=sys.stderr)
        return 2
    if args.excel_only:
        report = merge_scenarios(run_dir, project=args.project)
    else:
        ctx = RunContext(run_dir, run_dir / "input.pdf", settings, PromptSet(settings.prompts_dir),
                         _make_llm(settings, args.dry_run))
        only = set(args.screens.split(",")) if args.screens else None
        report = run_scenario(ctx, only, project=args.project)
    if report:
        s = report["summary"]
        print(f"\n[④ 결과] 시나리오 {s['scenarios']}개 · 단계 {s['steps']}개 · 단위 {s['units_covered']}/{s['units_target']}개 들어감 "
              f"(못 넣은 단위 {s['units_uncovered']}, 아직 안 돌린 단위 {s['units_not_run']}, 제약이라 뺀 단위 {s['units_excluded']}) · 경고 {s['warnings']}건")
        if report.get("spec_file"):
            print(f"  사양서: {run_dir / report['spec_file']}")
        if report.get("trace_file"):
            print(f"  추적표: {run_dir / report['trace_file']}")
        print("  자세한 내용: scenario_report.json, scenarios.json")
    return 0


def cmd_serve(args) -> int:
    from .server import ServeOptions, serve

    settings = Settings()
    return serve(args.host, args.port, ServeOptions(settings.output_dir, workers=args.workers, code_facts=args.code_facts))


def cmd_trace(args) -> int:
    from .trace import trace

    if not args.unit and not args.item:
        print("--unit 또는 --item 중 하나를 주세요", file=sys.stderr)
        return 2
    print(trace(Path(args.run), unit=args.unit, item=args.item))
    return 0


def cmd_score(args) -> int:
    from .score import format_report, score

    run_dir = Path(args.run)
    if not (run_dir / "judgments.json").exists():
        print("judgments.json이 없습니다. judge를 먼저 하세요", file=sys.stderr)
        return 2
    print(format_report(score(run_dir, Path(args.key))))
    return 0


def cmd_validate(args) -> int:
    obj = read_json(Path(args.screen_file))
    if args.screen_id == "APP":
        issues = schema.validate_app_profile(obj)
    else:
        issues = schema.validate_screen(obj, args.screen_id)
    for i in issues:
        print(f"[{i.level}] {i.where}: {i.message}")
    print(f"오류 {len(schema.errors(issues))}건, 전체 {len(issues)}건")
    return 1 if schema.errors(issues) else 0


def main(argv: list[str] | None = None) -> int:
    # 출력을 파일로 돌릴 때(한글 Windows는 cp949) 표시할 수 없는 글자가 있어도 멈추지 않게 한다.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    p = argparse.ArgumentParser(prog="specpilot", description="SpecPilot 백엔드 (입력 점검 → ① 앱 프로필 → 게이트 → ② 화면별 분해 → 합치기 → ③ 정합성 판정 / ④ 시나리오 합성)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="입력 점검만 (API 호출 없음)")
    c.add_argument("--pdf", required=True)
    c.add_argument("--app-profile", help="있으면 화면 단위 게이트 판정까지 본다")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("run", help="전체 실행")
    r.add_argument("--pdf", required=True)
    r.add_argument("--name", help="실행 폴더 이름 (기본: 날짜-시각)")
    r.add_argument("--app-profile", help="① 대신 쓸 기존 app_profile.json (②만 다시 돌릴 때)")
    r.add_argument("--screens", help="이 화면들만 실행. 쉼표로 구분")
    r.add_argument("--workers", type=int, default=1, help="② 동시 호출 수")
    r.add_argument("--dry-run", action="store_true", help="API를 부르지 않고 prompts_preview/에 프롬프트만 저장")
    r.add_argument("--force", action="store_true", help="입력 점검·게이트에서 반려돼도 그대로 실행")
    r.set_defaults(func=cmd_run)

    s = sub.add_parser("screen", help="기존 실행에서 화면 하나(또는 여러 개)만 다시 실행")
    s.add_argument("--run", required=True, help="output/<실행ID>")
    s.add_argument("--screen", required=True, help="화면 ID. 쉼표로 여러 개")
    s.add_argument("--pdf", help="고친 기획서 PDF (쪽 수가 같아야 함). 입력 점검을 다시 하고 이 PDF로 실행")
    s.add_argument("--force", action="store_true", help="게이트에서 반려돼도 그대로 실행")
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_screen)

    m = sub.add_parser("merge", help="합치기·검사만 다시")
    m.add_argument("--run", required=True)
    m.set_defaults(func=cmd_merge)

    j = sub.add_parser("judge", help="③ 정합성 판정 (run 결과 + 소스 코드)")
    j.add_argument("--run", required=True, help="output/<실행ID>")
    j.add_argument("--code", required=True, help="소스 코드 폴더")
    j.add_argument("--screens", help="이 화면들만. 쉼표로 구분")
    j.add_argument("--mode", choices=["auto", "whole", "screen"], default="auto",
                   help="auto: 크기를 재서 결정 / whole: 코드 전체 / screen: 화면별 묶음")
    j.add_argument("--facts", help="코드 분석 결과 JSON (코드팀 정적 분석). 형식: docs/code_facts.example.json")
    j.add_argument("--dry-run", action="store_true")
    j.set_defaults(func=cmd_judge)

    sn = sub.add_parser("scenario", help="④ 시나리오 합성 (run 결과로 테스트 사양서 만들기. 코드·판정 결과는 쓰지 않음)")
    sn.add_argument("--run", required=True, help="output/<실행ID>")
    sn.add_argument("--screens", help="이 화면(또는 APP)이 든 묶음만. 쉼표로 구분")
    sn.add_argument("--project", help="사양서 머리글의 프로젝트명 (기본: 기획서 파일 이름)")
    sn.add_argument("--excel-only", action="store_true", help="LLM을 부르지 않고 지난 결과로 scenarios.json과 엑셀만 다시 만든다")
    sn.add_argument("--dry-run", action="store_true")
    sn.set_defaults(func=cmd_scenario)

    sv = sub.add_parser("serve", help="시연용 로컬 서버 (웹에서 올린 기획서·코드로 run → judge → scenario를 끝까지 돌림)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8765, help="웹(frontend/vite.config.ts)이 /api를 넘기는 포트와 같아야 한다")
    sv.add_argument("--workers", type=int, default=2, help="② 동시 호출 수")
    sv.add_argument("--code-facts", action="store_true", help="③ 전에 code_analysis(자바 파서 등)를 돌려 --facts로 넣는다")
    sv.set_defaults(func=cmd_serve)

    t = sub.add_parser("trace", help="단위 하나를 기획서 원문 → 단위 → 판정·근거 코드까지 거슬러 보기")
    t.add_argument("--run", required=True)
    t.add_argument("--unit", help="단위 ID. 예: REQ-LOGIN-001-07")
    t.add_argument("--item", help='기획서 항목. 예: "LOGIN-001 Description 3"')
    t.set_defaults(func=cmd_trace)

    sc = sub.add_parser("score", help="③ 판정을 정답 세트와 비교해 채점 (조장용)")
    sc.add_argument("--run", required=True)
    sc.add_argument("--key", required=True, help="정답 세트 JSON (팀 저장소에 올리지 않는다)")
    sc.set_defaults(func=cmd_score)

    v = sub.add_parser("validate", help="JSON 파일 하나 검사")
    v.add_argument("--screen-file", required=True)
    v.add_argument("--screen-id", required=True, help="화면 ID. 앱 프로필이면 APP")
    v.set_defaults(func=cmd_validate)

    args = p.parse_args(argv)
    return args.func(args)
