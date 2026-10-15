"""사실을 화면별로 나눈다.

③은 화면마다 common + screens[화면ID]를 프롬프트에 넣는다. 화면과 관계없는 사실(보안, 전역 처리, 설정,
Spring Data)은 common으로, 나머지는 그 화면의 템플릿과 연결된 사실만 그 화면으로 보낸다.

화면 ↔ 템플릿 대응은 둘 중 하나(또는 둘 다)로 정한다.
1. --requirements (②까지 돈 실행의 requirements.json): 화면 단위의 원문 문구(exact.message), 값, 이동 대상,
   화면 이름이 템플릿 글자에 들어 있는 정도로 템플릿을 고른다. 백엔드의 files_mentioning처럼 공백·기호를 뺀
   앞 6글자를 비교해서, 문구가 조금 달라도(=불일치) 찾는다.
2. --code-map (③을 화면별 묶음으로 돌린 실행의 judge/code_map.json): 화면마다 고른 파일을 그대로 쓴다.

어느 화면에도 붙지 않은 사실은 버리지 않고 common에 넣는다.
둘 다 없으면 모든 사실을 common에 넣는다 (code_analysis/README.md의 "처음엔 전부 common에 넣어도 된다").
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .facts import Fact
from .java_facts import JavaFacts, Route
from .link import Linker, _match, _route_pattern
from .web_facts import norm_url

ID_LIKE = re.compile(r"^[A-Z]+-\d+$")


def _key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text or "")


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


class ScreenSplitter:
    def __init__(self, linker: Linker, jf: JavaFacts):
        self.lk = linker
        self.jf = jf
        self.matched: dict[str, list[str]] = {}       # 화면 → 고른 템플릿 경로 (기록용)
        self.anchors: dict[str, set[str]] = {}

    # ------------------------------------------------ 화면별 고리 만들기

    def from_requirements(self, path: Path, min_score: int = 3):
        req = read_json(path)
        profile = req.get("app_profile") or {}
        screens = [s for s in (profile.get("screens") or []) if s.get("screen_id")]
        units = req.get("units") or []
        views = [v for v in self.lk.templates if not self._is_layout(v)]
        body = {v: self._body_key(v) for v in views}
        scores: dict[str, dict[str, float]] = {}
        for s in screens:
            sid = s["screen_id"]
            sc = scores.setdefault(sid, {})
            popup = (s.get("type") or "") == "팝업"
            name_key = _key(re.sub(r"\(.*?\)", "", s.get("name") or ""))
            tokens = [_key(t) for t in re.sub(r"\(.*?\)", "", s.get("name") or "").split() if _key(t)]
            for v in views:
                t = self.lk.templates[v]
                if name_key and not popup:            # 팝업은 부모 화면 템플릿 제목과 겹치므로 이름으로 고르지 않는다
                    best = 0
                    for h in [t.title] + t.headings:
                        hk = _key(h)
                        if not hk:
                            continue
                        if hk == name_key:
                            best = max(best, 6)
                        elif tokens and all(tok in hk for tok in tokens):
                            best = max(best, 4)
                        elif len(hk) >= 2 and hk in name_key:   # 템플릿 제목이 화면 이름의 앞부분 (마이페이지 ⊂ 마이페이지 상세)
                            best = max(best, 3 if len(hk) >= 4 else 2)
                    sc[v] = sc.get(v, 0) + best
                for ph, w in self._phrases(sid, units):
                    k = _key(ph)
                    if len(k) < 2 or k.isdigit():
                        continue
                    if (k[:6] if len(k) >= 6 else k) in body[v]:
                        sc[v] = sc.get(v, 0) + w
        base = {sid: dict(sc) for sid, sc in scores.items()}
        popups = {s["screen_id"] for s in screens if (s.get("type") or "") == "팝업"}
        chosen = self._choose(scores, min_score)
        for _ in range(2):                            # 화면 이동으로 이어 찾기 (로그인 화면의 링크 → 그 링크가 여는 화면)
            added = set()
            for sid, v, label in self._navigation(profile, units, chosen):
                if sid in popups or (sid, v) in added:
                    continue
                has_base = any(x > 0 for x in base.get(sid, {}).values())
                if has_base and base[sid].get(v, 0) <= 0:   # 이미 후보가 있는 화면에는 후보를 새로 만들지 않고 밀어 주기만 한다
                    continue
                added.add((sid, v))
                scores.setdefault(sid, {})[v] = scores[sid].get(v, 0) + 5
            chosen = self._choose(scores, min_score)
        for sid in [s["screen_id"] for s in screens]:
            vs = chosen.get(sid, [])
            self.matched[sid] = [self.lk.templates[v].path for v in vs]
            self._add_templates(sid, vs)

    def _body_key(self, view: str) -> str:
        t = self.lk.templates[view]
        text = t.text
        for url, _ in t.scripts:                      # 템플릿이 불러오는 JS의 문구도 그 화면 글자로 본다
            jp = self.lk.js_path(url)
            if jp:
                text += "\n" + self.lk.code.text(jp)
        return _key(text)

    @staticmethod
    def _phrases(sid: str, units: list[dict]) -> list[tuple[str, int]]:
        out = []
        for u in units:
            if u.get("screen_id") != sid:
                continue
            ex = u.get("exact") or {}
            if ex.get("message"):
                out.append((ex["message"], 3))
            for v in ex.get("values") or []:
                if isinstance(v, str):
                    out.append((v, 1))
            t = ex.get("target")
            if isinstance(t, str) and not ID_LIKE.match(t):
                out.append((t, 1))
            for field_ in ("when", "then"):
                for q in re.findall(r"[\'\"‘“]([^\'\"’”]{2,30})[\'\"’”]", u.get(field_) or ""):
                    out.append((q, 2))
        return out

    @staticmethod
    def _choose(scores: dict[str, dict[str, float]], min_score: int) -> dict[str, list[str]]:
        out = {}
        for sid, sc in scores.items():
            sc = {v: x for v, x in sc.items() if x > 0}
            if not sc:
                continue
            best = max(sc.values())
            out[sid] = [v for v, x in sorted(sc.items(), key=lambda kv: -kv[1]) if x >= max(min_score, 0.6 * best)]
        return out

    def _navigation(self, profile: dict, units: list[dict], chosen: dict[str, list[str]]):
        """이미 찾은 화면의 버튼·링크 중, 설계서의 화면 이동(flows, 이동 단위의 target)과 라벨이 맞는 것을 따라가
        그 주소를 처리하는 경로가 보여 주는 템플릿을 이동 대상 화면의 후보로 낸다."""
        moves = [(f.get("from"), f.get("trigger") or "", f.get("to")) for f in (profile.get("flows") or [])]
        moves += [(u.get("screen_id"), u.get("when") or "", (u.get("exact") or {}).get("target"))
                  for u in units if ID_LIKE.match(str((u.get("exact") or {}).get("target") or ""))]
        for src, label, dst in moves:
            if not src or not dst or src == dst or not ID_LIKE.match(str(dst)):
                continue
            lk = _key(label)
            for v in chosen.get(src, []):
                for c in self.lk.templates[v].controls:
                    ck = _key(c.text)
                    if c.tag not in ("a", "button") or len(ck) < 2 or ck not in lk:
                        continue
                    if c.tag == "a":
                        method, url = "GET", norm_url(c.attrs.get("th:href") or c.attrs.get("href"))
                    else:
                        method, url = c.attrs.get("_form_method", "GET"), norm_url(c.attrs.get("_form_action"))
                    for view in self._opens(method, url, hops=1):
                        yield dst, view, label

    def _opens(self, method: str, url: str | None, hops: int) -> list[str]:
        """이 주소로 요청하면 정상 흐름에서 보이는 템플릿 (redirect는 한 번 따라간다)."""
        if not url:
            return []
        out = []
        for r in self.jf.routes:
            if r.http not in (method, "ANY") or not any(_match(_route_pattern(p), url) for p in r.paths):
                continue
            for x in r.returns:
                if x.context != "정상 흐름":
                    continue
                if x.kind in ("view", "forward") and x.value.strip("/") in self.lk.templates:
                    out.append(x.value.strip("/"))
                elif x.kind == "redirect" and hops > 0:
                    out += self._opens("GET", norm_url(x.value), hops - 1)
        return list(dict.fromkeys(out))

    def from_code_map(self, path: Path):
        cmap = read_json(path)
        for m in cmap.get("mapping") or []:
            sid = m.get("screen_id")
            files = [f for f in (m.get("files") or []) if f in self.lk.code.files]
            if not sid:
                continue
            views = [t.view for t in self.lk.templates.values() if t.path in files]
            self.matched.setdefault(sid, [])
            self.matched[sid] = sorted(set(self.matched[sid]) | set(files))
            a = self.anchors.setdefault(sid, set())
            a |= {f"file:{f}" for f in files}
            for f in files:                       # 고른 Java 파일의 경로·메서드·폼 클래스도 붙인다
                for c in self.jf.ix.files.get(f).classes if f in self.jf.ix.files else []:
                    a.add(f"class:{c.name}")
                    a |= {f"method:{m2.qname}" for m2 in c.methods}
                for r in self.jf.routes:
                    if r.method.file == f:
                        a.add(f"route:{r.label}")
            self._add_templates(sid, views)

    @staticmethod
    def _is_layout(view: str) -> bool:
        return view.startswith(("fragments/", "layout", "error/"))

    def _add_templates(self, sid: str, views: list[str]):
        a = self.anchors.setdefault(sid, set())
        routes: list[Route] = []
        for v in views:
            t = self.lk.templates.get(v)
            if t is None:
                continue
            a |= {f"file:{t.path}", f"view:{t.view}"}
            refs = list(t.url_refs)
            for url, _ in t.scripts:
                jp = self.lk.js_path(url)
                if jp:
                    a.add(f"file:{jp}")
                    refs += self.lk.js[jp].url_refs
            for r in self.jf.routes:
                renders = any(x.value.strip("/") == v for x in r.views())
                called = any(_match(_route_pattern(p), u) and (m == r.http or r.http == "ANY")
                             for p in r.paths for m, u, *_ in refs)
                if renders or called:
                    routes.append(r)
        for r in routes:
            a.add(f"route:{r.label}")
            a |= {f"class:{p.type}" for p in r.form_params}
            a |= self._methods_reached(r)

    def _methods_reached(self, r: Route) -> set[str]:
        """경로 처리 메서드에서 이어지는 서비스 메서드 (서비스 안의 호출까지 따라간다)."""
        out, todo, seen = set(), [r.method], set()
        while todo:
            m = todo.pop()
            if m.qname in seen:
                continue
            seen.add(m.qname)
            out.add(f"method:{m.qname}")
            for call in self.jf.ix.calls(m):
                todo += self.jf.ix.resolve_targets(call)      # 인터페이스면 구현 메서드 모두
        return out

    # ------------------------------------------------ 나누기

    def split(self, facts: list[Fact]) -> tuple[list[Fact], dict[str, list[Fact]], int]:
        common, screens, unplaced = [], {}, 0
        for f in facts:
            if f.common or not self.anchors:
                common.append(f)
                continue
            placed = False
            fa = f.all_anchors()
            for sid, a in self.anchors.items():
                if fa & a:
                    screens.setdefault(sid, []).append(f)
                    placed = True
            if not placed:
                common.append(f)
                unplaced += 1
        return common, screens, unplaced
