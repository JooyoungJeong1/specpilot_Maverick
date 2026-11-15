"""python -m code_analysis --code <샘플 코드 폴더> [--requirements ...] [--code-map ...]

1. 백엔드(.java + Thymeleaf): Java 분석기(analyzer/, JavaParser + Symbol Solver + Jsoup) → backend-analysis.json
2. 프론트엔드(.js): analyze_frontend_js.py (tree-sitter) → frontend-js.json
3. 두 결과와 설정 파일로 사실 문장을 만들고 화면별로 나눠 code_facts.json을 쓴다.
결과: code_analysis/out/code_facts.json (형식: backend/docs/code_facts.example.json)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from . import __version__, codebase
from .config_facts import config_facts
from .facts import check, write

OUT_DIR = Path(__file__).resolve().parent / "out"
DEFAULT_OUT = OUT_DIR / "code_facts.json"


def run_analyzer(code, jar: str | None, classpath: str | None, gradle: bool, log) -> dict:
    from . import analyzer_bridge as ab
    found = ab.find_jar(jar)
    if found is None:
        raise SystemExit("백엔드 분석기 jar가 없습니다. 먼저 한 번 빌드하세요:\n  " + ab.BUILD_HINT
                         + "\n(또는 --analyzer-jar 경로, 이미 만든 결과를 다시 쓰려면 --analysis out/backend-analysis.json)")
    if not ab.java_available():
        raise SystemExit("java 명령을 찾지 못했습니다. JDK 17 이상을 설치하고 PATH에 넣어 주세요.")
    log(f"백엔드 분석 중 ({found.name}, JavaParser + Symbol Solver + Jsoup)…")
    try:
        return ab.run(code, found, classpath=classpath, gradle_root=code.root if gradle else None)
    except RuntimeError as e:
        raise SystemExit(str(e))


def build(code_root: Path, requirements: Path | None = None, code_map: Path | None = None, log=print,
          jar: str | None = None, classpath: str | None = None, gradle: bool = False,
          analysis: dict | None = None) -> tuple[dict, list[str]]:
    try:
        from . import analyze_frontend_js
        from .backend_model import BackendModel
        from .facts_builder import FactsBuilder
        from .screens import ScreenSplitter
    except ImportError as e:      # tree-sitter가 없을 때 알아보기 쉬운 안내
        raise SystemExit(f"분석 도구를 불러오지 못했습니다 ({e}). 먼저 설치하세요: pip install -r code_analysis/requirements.txt")

    code = codebase.load(code_root)
    if not code.files:
        raise SystemExit(f"코드 파일을 찾지 못했습니다: {Path(code_root).resolve()}")
    log(f"코드 {len(code.files)}개 파일 (③과 같은 목록, 읽기 방식: {code.loader})")

    if analysis is None:
        analysis = run_analyzer(code, jar, classpath, gradle, log)
    model = BackendModel(analysis)
    stats = model.resolution_stats()
    log(f"  호출 {len(model.calls)}개: 분석기 판정 {stats['analyzer_notes']}, 라이브러리 jar {stats['library_jars']}개")
    js = analyze_frontend_js.analyze(code)
    log(f"프론트엔드 JS {len(js)}개 분석 (tree-sitter)")

    fb = FactsBuilder(code, model, js)
    facts, problems = check(fb.run() + config_facts(code), code)

    sp = ScreenSplitter(fb)
    how = []
    if requirements:
        sp.from_requirements(requirements)
        how.append("requirements")
    if code_map:
        sp.from_code_map(code_map)
        how.append("code_map")
    common, screens, unplaced = sp.split(facts)
    from .reach import build_reach
    reach = build_reach(fb, sp, facts)          # ③ 근거 재확인용 (프롬프트에는 넣지 않음)

    counts: dict[str, int] = {}
    for f in facts:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    meta = {
        "tool": f"code_analysis {__version__}",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "code_root": str(Path(code_root).resolve()),
        "code_files": len(code.files),
        "codebase_loader": code.loader,
        "backend_analyzer": analysis.get("tool"),
        "call_resolution": stats,
        "screen_split": "+".join(how) or "none (전부 common)",
        "facts_total": len(facts),
        "facts_by_kind": counts,
        "common_count": len(common),
        "unplaced_to_common": unplaced,
        "screen_templates": sp.matched,
        "screens_without_template": sorted(s for s, v in sp.matched.items() if not v),
        "dropped": problems,
        "reach": {"methods": len(reach["methods"]), "screens": len(reach["screens"]), "unused": len(reach["unused"])},
    }
    return {"common": common, "screens": screens, "meta": meta, "reach": reach, "facts": facts, "analysis": analysis, "js": js}, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m code_analysis",
                                 description="소스 코드에서 ③ 정합성 판정에 같이 줄 사실을 뽑아 code_facts.json을 만든다")
    ap.add_argument("--code", required=True, help="샘플 코드 폴더. judge --code 에 주는 폴더와 같아야 한다")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"결과 파일 (기본: {DEFAULT_OUT})")
    ap.add_argument("--requirements", help="②까지 돈 실행의 requirements.json. 주면 사실을 화면별로 나눈다")
    ap.add_argument("--code-map", help="③ 화면별 묶음 실행의 judge/code_map.json. 주면 그 대응표로 화면별로 나눈다")
    ap.add_argument("--analyzer-jar", help="백엔드 분석기 jar (기본: code_analysis/analyzer/target/ 에서 찾음)")
    ap.add_argument("--classpath", help="라이브러리 jar 목록 파일 (한 줄에 하나). 주면 Spring·JPA 라이브러리 메서드까지 푼다")
    ap.add_argument("--gradle", action="store_true", help="샘플 코드의 gradlew로 라이브러리 classpath를 뽑아 쓴다 (몇 분 걸릴 수 있음)")
    ap.add_argument("--analysis", help="이미 만든 backend-analysis.json을 다시 쓴다 (Java 분석을 건너뜀)")
    args = ap.parse_args(argv)

    analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8")) if args.analysis else None
    result, problems = build(Path(args.code), Path(args.requirements) if args.requirements else None,
                             Path(args.code_map) if args.code_map else None, jar=args.analyzer_jar,
                             classpath=args.classpath, gradle=args.gradle, analysis=analysis)
    out = Path(args.out)
    obj = write(out, result["common"], result["screens"], result["meta"], result["reach"])
    side = out.parent                                  # 중간 결과 (사람이 확인하는 용도, 커밋하지 않음)
    (side / "backend-analysis.json").write_text(json.dumps(result["analysis"], ensure_ascii=False, indent=1), encoding="utf-8")
    (side / "frontend-js.json").write_text(json.dumps(result["js"], ensure_ascii=False, indent=1), encoding="utf-8")

    meta = result["meta"]
    print(f"사실 {meta['facts_total']}개 → common {meta['common_count']}개, 화면 {len(obj['screens'])}개")
    print("  종류별: " + ", ".join(f"{k} {v}" for k, v in sorted(meta["facts_by_kind"].items())))
    print("  호출 대상: " + ", ".join(f"{k} {v}" for k, v in meta["call_resolution"]["target_by"].items()))
    if meta["screen_split"].startswith("none"):
        print("  화면별로 나누지 않았습니다 (--requirements 또는 --code-map을 주면 나눔)")
    else:
        for sid, files in sorted(meta["screen_templates"].items()):
            print(f"  {sid}: 사실 {len(obj['screens'].get(sid, []))}개, 대응 {', '.join(f.split('/')[-1] for f in files) or '찾지 못함'}")
        if meta["unplaced_to_common"]:
            print(f"  어느 화면에도 붙지 않아 common에 넣은 사실 {meta['unplaced_to_common']}개")
    r = meta["reach"]
    print(f"  근거 재확인용 도달 정보: 메서드 {r['methods']}개, 화면 {r['screens']}개, 미사용 후보 {r['unused']}곳")
    for p in problems:
        print(f"  [뺌] {p}", file=sys.stderr)
    print(f"저장: {out.resolve()} (중간 결과: backend-analysis.json, frontend-js.json)")
    return 0
