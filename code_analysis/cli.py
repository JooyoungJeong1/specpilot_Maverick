"""python -m code_analysis --code <샘플 코드 폴더> [--requirements ...] [--code-map ...]

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

DEFAULT_OUT = Path(__file__).resolve().parent / "out" / "code_facts.json"


def choose_resolver(code, engine: str, jar: str | None, classpath: str | None, gradle: bool, log):
    """Java 호출 해석 엔진 고르기. (resolver 또는 None, 실제로 쓴 엔진 설명)"""
    from . import javaparser_bridge as jpb
    if engine == "treesitter":
        return None, "treesitter (간이 타입 해석)"
    found = jpb.find_jar(jar)
    problem = None
    if found is None:
        problem = ("JavaParser 해석기 jar가 없습니다. 한 번 빌드하세요: "
                   "cd code_analysis/javaparser && mvn -q package")
    elif not jpb.java_available():
        problem = "java 명령을 찾지 못했습니다 (JDK 17 이상 설치 필요)"
    if problem is None:
        try:
            log(f"JavaParser로 호출 해석 중… ({found.name})")
            resolver = jpb.run(code, found, classpath=classpath, gradle_root=code.root if gradle else None)
            st = resolver.stats
            log(f"  호출 {st.get('calls')}개 중 {st.get('resolved')}개 해석, 이 코드 안의 선언으로 {st.get('resolved_to_source')}개")
            return resolver, f"javaparser ({resolver.data.get('tool')}, 라이브러리 jar {resolver.data.get('library_jars', 0)}개)"
        except RuntimeError as e:
            problem = str(e)
    if engine == "javaparser":
        raise SystemExit(problem)
    log(f"  [알림] {problem.splitlines()[0]} → tree-sitter 간이 해석으로 진행합니다")
    return None, f"treesitter (JavaParser를 쓰지 못함: {problem.splitlines()[0]})"


def build(code_root: Path, requirements: Path | None = None, code_map: Path | None = None,
          log=print, engine: str = "treesitter", jar: str | None = None, classpath: str | None = None,
          gradle: bool = False, resolver=None) -> tuple[dict, list[str]]:
    try:
        from .java_index import JavaIndex
        from .java_facts import JavaFacts
        from .link import Linker
        from .screens import ScreenSplitter
    except ImportError as e:      # tree-sitter가 없을 때 알아보기 쉬운 안내
        raise SystemExit(f"분석 도구를 불러오지 못했습니다 ({e}). 먼저 설치하세요: pip install -r code_analysis/requirements.txt")

    code = codebase.load(code_root)
    if not code.files:
        raise SystemExit(f"코드 파일을 찾지 못했습니다: {Path(code_root).resolve()}")
    log(f"코드 {len(code.files)}개 파일 (③과 같은 목록, 읽기 방식: {code.loader})")

    if resolver is not None:
        engine_desc = "javaparser (주어진 해석 결과)"
    else:
        resolver, engine_desc = choose_resolver(code, engine, jar, classpath, gradle, log)
    ix = JavaIndex(code, resolver)
    jf = JavaFacts(ix).run()
    lk = Linker(code, jf).run()
    facts, problems = check(jf.facts + lk.facts + config_facts(code), code)

    sp = ScreenSplitter(lk, jf)
    how = []
    if requirements:
        sp.from_requirements(requirements)
        how.append("requirements")
    if code_map:
        sp.from_code_map(code_map)
        how.append("code_map")
    common, screens, unplaced = sp.split(facts)

    counts: dict[str, int] = {}
    for f in facts:
        counts[f.kind] = counts.get(f.kind, 0) + 1
    meta = {
        "tool": f"code_analysis {__version__}",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "code_root": str(Path(code_root).resolve()),
        "code_files": len(code.files),
        "codebase_loader": code.loader,
        "java_engine": engine_desc,
        "call_resolution": ix.resolution_stats(),
        "screen_split": "+".join(how) or "none (전부 common)",
        "facts_total": len(facts),
        "facts_by_kind": counts,
        "common_count": len(common),
        "unplaced_to_common": unplaced,
        "screen_templates": sp.matched,
        "screens_without_template": sorted(s for s, v in sp.matched.items() if not v),
        "dropped": problems,
    }
    return {"common": common, "screens": screens, "meta": meta, "disagreements": ix.disagreements,
            "facts": facts}, problems


def compare(args, log=print) -> int:
    """같은 코드를 두 엔진으로 분석해 달라지는 사실과 호출 해석을 out/engine_compare.json에 남긴다."""
    req = Path(args.requirements) if args.requirements else None
    cmap = Path(args.code_map) if args.code_map else None
    ts, _ = build(Path(args.code), req, cmap, log=lambda *a: None, engine="treesitter")
    jp, _ = build(Path(args.code), req, cmap, log=log, engine="javaparser", jar=args.jar,
                  classpath=args.classpath, gradle=args.gradle)
    key = lambda f: (f.kind, f.file, f.line, f.fact)
    a, b = {key(f) for f in ts["facts"]}, {key(f) for f in jp["facts"]}
    only_ts = sorted(a - b)
    only_jp = sorted(b - a)
    obj = {
        "_설명": "tree-sitter 간이 해석과 JavaParser 해석의 차이. only_*는 한쪽 결과에만 있는 사실, "
                "call_disagreements는 같은 호출을 다른 클래스로 푼 경우다.",
        "javaparser": jp["meta"]["java_engine"],
        "call_resolution": jp["meta"]["call_resolution"],
        "facts": {"treesitter": len(a), "javaparser": len(b), "same": len(a & b)},
        "only_treesitter": [dict(zip(("kind", "file", "line", "fact"), x)) for x in only_ts],
        "only_javaparser": [dict(zip(("kind", "file", "line", "fact"), x)) for x in only_jp],
        "call_disagreements": jp["disagreements"],
    }
    out = Path(args.out).parent / "engine_compare.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log(f"사실: tree-sitter {len(a)}개, JavaParser {len(b)}개, 같은 것 {len(a & b)}개")
    log(f"  tree-sitter에만 {len(only_ts)}개, JavaParser에만 {len(only_jp)}개, 호출 해석이 다른 곳 {len(jp['disagreements'])}개")
    for x in jp["disagreements"][:10]:
        log(f"    {x}")
    log(f"저장: {out.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m code_analysis",
                                 description="소스 코드에서 ③ 정합성 판정에 같이 줄 사실을 뽑아 code_facts.json을 만든다")
    ap.add_argument("--code", required=True, help="샘플 코드 폴더. judge --code 에 주는 폴더와 같아야 한다")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"결과 파일 (기본: {DEFAULT_OUT})")
    ap.add_argument("--requirements", help="②까지 돈 실행의 requirements.json. 주면 사실을 화면별로 나눈다")
    ap.add_argument("--code-map", help="③ 화면별 묶음 실행의 judge/code_map.json. 주면 그 대응표로 화면별로 나눈다")
    ap.add_argument("--java-engine", choices=["auto", "javaparser", "treesitter"], default="auto",
                    help="Java 호출 해석. auto: JavaParser 해석기 jar와 java가 있으면 JavaParser, 없으면 tree-sitter (기본)")
    ap.add_argument("--jar", help="JavaParser 해석기 jar 경로 (기본: code_analysis/javaparser/target/ 에서 찾음)")
    ap.add_argument("--classpath", help="라이브러리 jar 목록 파일 (한 줄에 하나). 주면 라이브러리 타입까지 푼다")
    ap.add_argument("--gradle", action="store_true", help="샘플 코드의 gradlew로 라이브러리 classpath를 뽑아 쓴다 (몇 분 걸릴 수 있음)")
    ap.add_argument("--compare-engines", action="store_true",
                    help="tree-sitter와 JavaParser 결과를 비교해 out/engine_compare.json에 남긴다 (code_facts.json은 만들지 않음)")
    args = ap.parse_args(argv)

    if args.compare_engines:
        return compare(args)
    result, problems = build(Path(args.code), Path(args.requirements) if args.requirements else None,
                             Path(args.code_map) if args.code_map else None, engine=args.java_engine,
                             jar=args.jar, classpath=args.classpath, gradle=args.gradle)
    out = Path(args.out)
    obj = write(out, result["common"], result["screens"], result["meta"])
    meta = result["meta"]
    print(f"Java 호출 해석: {meta['java_engine']} {meta['call_resolution']['by_source']}")
    print(f"사실 {meta['facts_total']}개 → common {meta['common_count']}개, 화면 {len(obj['screens'])}개")
    print("  종류별: " + ", ".join(f"{k} {v}" for k, v in sorted(meta["facts_by_kind"].items())))
    if meta["screen_split"].startswith("none"):
        print("  화면별로 나누지 않았습니다 (--requirements 또는 --code-map을 주면 나눔)")
    else:
        for sid, files in sorted(meta["screen_templates"].items()):
            print(f"  {sid}: 사실 {len(obj['screens'].get(sid, []))}개, 대응 {', '.join(f.split('/')[-1] for f in files) or '찾지 못함'}")
        if meta["unplaced_to_common"]:
            print(f"  어느 화면에도 붙지 않아 common에 넣은 사실 {meta['unplaced_to_common']}개")
    for p in problems:
        print(f"  [뺌] {p}", file=sys.stderr)
    print(f"저장: {out.resolve()}")
    return 0
