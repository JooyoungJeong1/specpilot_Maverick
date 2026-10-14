"""①② 출력 검사와 후처리 (프롬프트 v3.1 형식).

error   → 재시도 사유 (형식이 틀려 다음 단계에서 쓸 수 없거나, 근거를 지어냄)
warning → 기록만 남김
fix     → 프로그램이 직접 고친 것 (예: 근거가 약한 함의를 질문으로 옮김, 화면 ID를 붙임)

v3.1에서 LLM은 응답 안에서만 쓰는 번호(key: u01, a01, q01)를 쓰고,
최종 ID(REQ-…, Q-…)는 assign_ids가 붙인다.
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict, dataclass

from .pdf_utils import squash

KINDS = {"표시", "검증", "상태", "이동", "처리", "실패", "접근", "제약"}
ORIGINS = {"명시", "함의"}
PRIORITIES = {"상", "하"}
UNIT_FIELDS = ["key", "screen_id", "source", "quote", "origin", "reason", "kind",
               "given", "when", "conditions", "then", "exact", "issue"]          # ref_hint는 없으면 null로 본다
EXACT_FIELDS = ["message", "values", "target"]
QUESTION_FIELDS = ["key", "topic", "question", "why", "related_units"]          # priority는 없으면 "하"
PROFILE_FIELDS = ["screens", "flows", "common_areas", "login_required", "roles", "role_limited",
                  "units", "questions"]
SCREEN_META_FIELDS = ["screen_id", "name", "pages"]

SOURCE_DESC = re.compile(r"Description\s*(\d+)")
SOURCE_ACTION = re.compile(r"Action(?:\s*/\s*Event)?\s*([A-Z])\b")
SCREEN_PREFIX = re.compile(r"^([A-Z][A-Z0-9]*-\d{2,})\s+(.*)$", re.S)
CAUSAL = re.compile(r"므로|때문|니까|으니|따라서|그래서")


@dataclass
class Issue:
    level: str      # "error" | "warning" | "fix"
    where: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def errors(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level == "error"]


def _where(item, fallback: str) -> str:
    if not isinstance(item, dict):
        return fallback
    return str(item.get("id") or item.get("key") or fallback)


def item_names(text: str) -> set[str]:
    """글자에서 기획서 항목 이름을 뽑는다. "Description 2-(1)" → {"Description 2"}."""
    return ({f"Description {int(n)}" for n in SOURCE_DESC.findall(text)}
            | {f"Action {a}" for a in SOURCE_ACTION.findall(text)})


# ---------- 단위 / 질문 ----------

def check_unit(u: dict, scope: str) -> list[Issue]:
    """scope: 화면 ID 또는 "APP"."""
    where = _where(u, "(key 없음)")
    if not isinstance(u, dict):
        return [Issue("error", "(단위 아님)", "단위가 객체가 아닙니다")]
    out: list[Issue] = []
    missing = [f for f in UNIT_FIELDS if f not in u]
    if missing:
        out.append(Issue("error", where, f"필드 누락: {', '.join(missing)}"))
    if "key" in u:
        prefix = "a" if scope == "APP" else "u"
        if not isinstance(u["key"], str) or not re.fullmatch(rf"{prefix}\d{{2,}}", u["key"]):
            out.append(Issue("warning", where, f"key 형식이 '{prefix}01' 꼴이 아닙니다: {u['key']}"))
    if "screen_id" in u and u["screen_id"] != scope:
        out.append(Issue("error", where, f"screen_id가 '{scope}'가 아닙니다: {u['screen_id']}"))
    if "kind" in u and u["kind"] not in KINDS:
        out.append(Issue("error", where, f"kind 값이 허용 목록에 없습니다: {u['kind']}"))
    if "origin" in u and u["origin"] not in ORIGINS:
        out.append(Issue("error", where, f"origin 값이 허용 목록에 없습니다: {u['origin']}"))
    if "source" in u and (not isinstance(u["source"], list) or not u["source"]):
        out.append(Issue("error", where, "source는 비어 있지 않은 목록이어야 합니다"))
    if "conditions" in u and not isinstance(u["conditions"], list):
        out.append(Issue("error", where, "conditions는 목록이어야 합니다"))
    if "then" in u and _is_blank(u["then"]):
        out.append(Issue("error", where, "then이 비어 있습니다"))
    if "exact" in u:
        ex = u["exact"]
        if not isinstance(ex, dict) or any(f not in ex for f in EXACT_FIELDS):
            out.append(Issue("error", where, "exact에는 message, values, target이 모두 있어야 합니다"))
        elif not isinstance(ex["values"], list):
            out.append(Issue("error", where, "exact.values는 목록이어야 합니다"))
    if u.get("origin") == "명시" and not _is_blank(u.get("reason")):
        out.append(Issue("warning", where, "명시 단위인데 reason이 있습니다"))
    rh = u.get("ref_hint")
    if rh is not None and (not isinstance(rh, dict) or "screen_id" not in rh or "value" not in rh):
        out.append(Issue("warning", where, "ref_hint는 null이거나 {screen_id, source, value}여야 합니다"))
    return out


def check_question(q: dict, scope: str) -> list[Issue]:
    where = _where(q, "(key 없음)")
    if not isinstance(q, dict):
        return [Issue("error", "(질문 아님)", "질문이 객체가 아닙니다")]
    out: list[Issue] = []
    missing = [f for f in QUESTION_FIELDS if f not in q]
    if missing:
        out.append(Issue("error", where, f"필드 누락: {', '.join(missing)}"))
    if "key" in q and (not isinstance(q["key"], str) or not re.fullmatch(r"q\d{2,}", q["key"])):
        out.append(Issue("warning", where, f"key 형식이 'q01' 꼴이 아닙니다: {q['key']}"))
    if q.get("priority") not in PRIORITIES:
        out.append(Issue("warning", where, f"priority가 상/하가 아닙니다: {q.get('priority')} (하로 둠)"))
    if "related_units" in q and not isinstance(q["related_units"], list):
        out.append(Issue("error", where, "related_units는 목록이어야 합니다"))
    return out


def duplicate_keys(items: list, label: str, field: str = "key") -> list[Issue]:
    seen, out = set(), []
    for it in items:
        k = it.get(field) if isinstance(it, dict) else None
        if k is None:
            continue
        if k in seen:
            out.append(Issue("error", str(k), f"{label} {field}가 중복됩니다"))
        seen.add(k)
    return out


def duplicate_ids(items: list, label: str) -> list[Issue]:
    return duplicate_keys(items, label, "id")


def _unknown_related(units: list, questions: list) -> list[Issue]:
    keys = {u.get("key") for u in units if isinstance(u, dict)}
    out = []
    for q in questions:
        if isinstance(q, dict) and isinstance(q.get("related_units"), list):
            unknown = [k for k in q["related_units"] if k not in keys]
            if unknown:
                out.append(Issue("warning", _where(q, "질문"),
                                 f"related_units에 이 응답에 없는 단위 key가 있습니다: {', '.join(map(str, unknown))} (뺌)"))
    return out


# ---------- 원문 대조 (quote, exact.message) ----------

def quote_segments(quote) -> list[str]:
    """함의 단위의 근거 원문들. " / "로 이어져 있다."""
    if _is_blank(quote):
        return []
    return [s.strip() for s in str(quote).split(" / ") if s.strip()]


def _pieces(text: str) -> list[str]:
    """대조할 조각. 줄임표(…, ...)로 끊긴 인용은 조각마다 본다."""
    out = []
    for seg in quote_segments(text):
        out += [p.strip() for p in re.split(r"…|\.\.\.+", seg) if len(squash(p)) >= 3]
    return out


def _find(texts, piece: str, pages: list[int] | None):
    found = texts.find(piece, pages)
    if found != "exact" and pages:
        wider = texts.find(piece)              # 함의 단위는 다른 화면 원문을 근거로 댈 수 있다
        if wider == "exact" or (wider == "approx" and found is None):
            found = wider
    return found


def check_quotes(units: list, texts, pages: list[int] | None, strict: bool = True) -> list[Issue]:
    """quote와 exact.message가 설계서 원문에 있는지 본다 (띄어쓰기·따옴표 모양은 무시).
    없으면 지어낸 근거로 보고 error(재시도), 한두 글자만 다르면 warning(오타를 고쳐 썼을 수 있음).
    그림이나 상태 화면이 근거인 단위, pdftotext 없이 읽은 경우는 원문 대조가 부정확하므로 warning만 남긴다."""
    if texts is None:
        return []
    out: list[Issue] = []
    for u in units:
        if not isinstance(u, dict):
            continue
        where = _where(u, "(단위)")
        sources = " ".join(map(str, u.get("source") or []))
        soft = (not strict or not texts.strong
                or any(w in sources for w in ("이미지", "그림", "상태 화면")))
        ex = u.get("exact") if isinstance(u.get("exact"), dict) else {}
        for label, text in (("quote", u.get("quote")), ("exact.message", ex.get("message"))):
            if _is_blank(text):
                continue
            for piece in _pieces(str(text)):
                found = _find(texts, piece, pages)
                if found == "approx":
                    out.append(Issue("warning", where, f"{label}가 원문과 한두 글자 다릅니다(오타를 고쳤을 수 있음): '{piece}'"))
                elif found is None:
                    out.append(Issue("warning" if soft else "error", where,
                                     f"{label}가 설계서 원문에 없습니다: '{piece}'. "
                                     "원문을 고치거나 줄이지 말고, 이어진 부분을 그대로 옮기세요"))
    return out


# ---------- 커버리지 ----------

def covered_items(screen_obj: dict, screen_id: str | None = None) -> set[str]:
    """단위의 source와 skipped의 source에 적힌 이 화면의 기획서 항목. 다른 화면 ID가 붙은 source는 뺀다."""
    texts: list[str] = []
    for u in screen_obj.get("units", []) or []:
        if isinstance(u, dict) and isinstance(u.get("source"), list):
            texts += [str(s) for s in u["source"]]
    for s in screen_obj.get("skipped", []) or []:
        if isinstance(s, dict):
            texts.append(str(s.get("source", "")))
    found: set[str] = set()
    for t in texts:
        m = SCREEN_PREFIX.match(t.strip())
        if m and screen_id and m.group(1) != screen_id:
            continue
        found |= item_names(t)
    return found


def check_coverage(screen_obj: dict, expected: set[str], strict: bool, screen_id: str | None = None) -> list[Issue]:
    sid = screen_id or str(screen_obj.get("screen_id"))
    missing = sorted(expected - covered_items(screen_obj, sid))
    if not missing:
        return []
    return [Issue("error" if strict else "warning", sid,
                  f"기획서 항목이 units·skipped 어디에도 없습니다: {', '.join(missing)}")]


def check_items_seen(screen_obj: dict, expected: set[str] | None, strict: bool, screen_id: str) -> list[Issue]:
    """세 군데 대조: 프로그램 체크리스트(expected) / 모델이 본 항목(items_seen) / 실제로 다룬 항목(units·skipped)."""
    seen: set[str] = set()
    for s in screen_obj.get("items_seen", []) or []:
        seen |= item_names(str(s))
    covered = covered_items(screen_obj, screen_id)
    out: list[Issue] = []
    lost = sorted(seen - covered)
    if lost:
        out.append(Issue("error" if strict else "warning", screen_id,
                         f"items_seen에 적은 항목이 units·skipped에 없습니다: {', '.join(lost)}"))
    if expected:
        unseen = sorted(expected - seen)
        if unseen:
            out.append(Issue("warning", screen_id, f"프로그램이 찾은 항목인데 items_seen에 없습니다: {', '.join(unseen)}"))
        extra = sorted(seen - expected)
        if extra:
            out.append(Issue("warning", screen_id,
                             f"프로그램 체크리스트에 없는 항목입니다(추출이 놓쳤거나 없는 번호): {', '.join(extra)}"))
    return out


# ---------- ① / ② 출력 전체 ----------

def normalize_app_profile(obj: dict) -> list[Issue]:
    """검사 전에 프로그램이 채우는 것: 화면 ID가 없는 화면에 ID 붙이기, 빠진 선택 필드 기본값."""
    fixes: list[Issue] = []
    if not isinstance(obj, dict):
        return fixes
    obj.setdefault("reading_notes", [])
    screens = obj.get("screens") if isinstance(obj.get("screens"), list) else []
    used = {s.get("screen_id") for s in screens if isinstance(s, dict)}
    n = 0
    for s in screens:
        if not isinstance(s, dict):
            continue
        s.setdefault("repeats_from", None)
        if _is_blank(s.get("screen_id")):
            n += 1
            while f"SCR-{n:03d}" in used:
                n += 1
            s["screen_id"] = f"SCR-{n:03d}"
            s["id_assigned"] = True              # 기획서에 화면 ID가 없어 프로그램이 붙임
            used.add(s["screen_id"])
            fixes.append(Issue("fix", s["screen_id"], f"화면 ID가 없어 {s['screen_id']}를 붙임 ({s.get('name')})"))
    return fixes


def validate_app_profile(obj: dict, page_total: int | None = None, texts=None, quote_strict: bool = True) -> list[Issue]:
    out: list[Issue] = []
    missing = [f for f in PROFILE_FIELDS if f not in obj]
    if missing:
        out.append(Issue("error", "app_profile", f"필드 누락: {', '.join(missing)}"))
    screens = obj.get("screens")
    if not isinstance(screens, list) or not screens:
        out.append(Issue("error", "app_profile", "screens가 비어 있습니다"))
        screens = []
    ids = []
    for s in screens:
        sid = s.get("screen_id") if isinstance(s, dict) else None
        where = f"screens/{sid}"
        if not isinstance(s, dict) or any(f not in s for f in SCREEN_META_FIELDS) or _is_blank(sid):
            out.append(Issue("error", where, f"화면 정보에 {', '.join(SCREEN_META_FIELDS)}가 모두 있어야 합니다"))
            continue
        ids.append(sid)
        pages = s.get("pages")
        if not isinstance(pages, list) or not pages or not all(isinstance(p, int) for p in pages):
            out.append(Issue("error", where, "pages는 정수 목록이어야 합니다"))
        elif page_total and any(p < 1 or p > page_total for p in pages):
            out.append(Issue("error", where, f"pages가 PDF 범위(1~{page_total})를 벗어납니다: {pages}"))
        rf = s.get("repeats_from")
        if rf is not None and (not isinstance(rf, dict) or not isinstance(rf.get("items"), list)):
            out.append(Issue("warning", where, "repeats_from은 null이거나 {screen_id, items}여야 합니다"))
    if len(ids) != len(set(ids)):
        out.append(Issue("error", "app_profile", "screens에 같은 screen_id가 두 번 이상 있습니다"))
    for ca in obj.get("common_areas", []) or []:
        if isinstance(ca, dict) and not isinstance(ca.get("described_scope", []), list):
            out.append(Issue("warning", f"common_areas/{ca.get('name')}", "described_scope는 목록이어야 합니다"))
    if not isinstance(obj.get("reading_notes", []), list):
        out.append(Issue("warning", "app_profile", "reading_notes는 목록이어야 합니다"))
    units = obj.get("units", []) or []
    questions = obj.get("questions", []) or []
    for u in units:
        out += check_unit(u, "APP")
    for q in questions:
        out += check_question(q, "APP")
    out += duplicate_keys(units, "단위")
    out += duplicate_keys(questions, "질문")
    out += _unknown_related(units, questions)
    out += check_quotes(units, texts, None, quote_strict)
    return out


def validate_screen(obj: dict, screen_id: str, expected: set[str] | None = None,
                    coverage_strict: bool = True, texts=None, pages: list[int] | None = None,
                    quote_strict: bool = True) -> list[Issue]:
    out: list[Issue] = []
    if obj.get("screen_id") != screen_id:
        out.append(Issue("error", screen_id, f"출력의 screen_id가 다릅니다: {obj.get('screen_id')}"))
    if not _is_blank(obj.get("reject_reason")):
        # 모델이 화면을 읽을 수 없다고 판단함. 분해 결과는 쓰지 않으므로 나머지는 검사하지 않는다.
        if obj.get("units"):
            out.append(Issue("warning", screen_id, "reject_reason이 있는데 units가 있습니다 (쓰지 않음)"))
        return out
    for key in ("units", "questions", "skipped", "items_seen"):
        if not isinstance(obj.get(key), list):
            out.append(Issue("error", screen_id, f"{key}가 목록이 아닙니다"))
    if errors(out):
        return out
    for u in obj["units"]:
        out += check_unit(u, screen_id)
    for q in obj["questions"]:
        out += check_question(q, screen_id)
    for s in obj["skipped"]:
        if not isinstance(s, dict) or "source" not in s or "reason" not in s:
            out.append(Issue("error", screen_id, "skipped 항목에는 source와 reason이 있어야 합니다"))
    out += duplicate_keys(obj["units"], "단위")
    out += duplicate_keys(obj["questions"], "질문")
    out += _unknown_related(obj["units"], obj["questions"])
    if expected:
        out += check_coverage(obj, expected, coverage_strict, screen_id)
    out += check_items_seen(obj, expected, coverage_strict, screen_id)
    out += check_quotes(obj["units"], texts, pages, quote_strict)
    return out


# ---------- 후처리: ID 붙이기, 함의 거르기 ----------

def _numbered(scope: str, prefix: str, items: list) -> int:
    nums = [int(m.group(1)) for it in items if isinstance(it, dict)
            and (m := re.fullmatch(rf"{prefix}-{re.escape(scope)}-(\d+)", str(it.get("id", ""))))]
    return max(nums, default=0)


def assign_ids(units: list[dict], questions: list[dict], scope: str) -> tuple[list[dict], list[dict]]:
    """key(u01, a01, q01) 대신 최종 ID를 붙인다. related_units의 key도 ID로 바꾼다. 순서는 응답 그대로 둔다."""
    key_to_id: dict[str, str] = {}
    new_units = []
    for n, u in enumerate(units, 1):
        uid = f"REQ-{scope}-{n:02d}"
        if u.get("key") is not None:
            key_to_id.setdefault(str(u["key"]), uid)
        u = {"id": uid, **{k: v for k, v in u.items() if k != "id"}}
        u.setdefault("ref_hint", None)
        new_units.append(u)
    new_questions = []
    for n, q in enumerate(questions, 1):
        q = {"id": f"Q-{scope}-{n:02d}", **{k: v for k, v in q.items() if k != "id"}}
        q["related_units"] = [key_to_id[str(k)] for k in q.get("related_units") or [] if str(k) in key_to_id]
        if q.get("priority") not in PRIORITIES:
            q["priority"] = "하"
        new_questions.append(q)
    return new_units, new_questions


def gate_implied(units: list[dict], questions: list[dict], scope: str, texts=None) -> tuple[list, list, list[Issue]]:
    """함의 단위의 근거를 확인한다. 못 채우면 단위에서 빼서 질문으로 옮긴다 (지우지 않는다).

    통과 조건: quote에 서로 다른 근거 원문이 둘 이상(" / "로 이음), 각 원문이 설계서에 있음, reason이 있음,
    "확신 낮음" 표시가 없음. 질문으로 옮긴 단위는 질문의 draft_unit에 그대로 남겨, 기획자가 답하면 되살릴 수 있다.
    같은 내용의 질문이 이미 있으면(그 질문의 related_units가 이 단위) 새 질문을 만들지 않고 그 질문에 붙인다.
    """
    questions = [dict(q) for q in questions]
    kept, fixes = [], []
    next_no = _numbered(scope, "Q", questions) + 1
    for u in units:
        if not isinstance(u, dict) or u.get("origin") != "함의":
            kept.append(u)
            continue
        reasons = []
        segs = {squash(s) for s in quote_segments(u.get("quote"))} - {""}
        if _is_blank(u.get("quote")) or _is_blank(u.get("reason")):
            reasons.append("근거 원문이나 추론이 비어 있음")
        elif len(segs) < 2:
            reasons.append("근거 원문이 하나뿐임")
        elif texts is not None and texts.strong and any(texts.find(s) is None for s in quote_segments(u.get("quote"))):
            reasons.append("근거 원문을 설계서에서 찾지 못함")
        if "확신 낮음" in str(u.get("issue") or ""):
            reasons.append("확신 낮음으로 표시됨")
        if not reasons:
            if not CAUSAL.search(str(u.get("reason"))):
                fixes.append(Issue("warning", _where(u, "단위"), "reason이 'A이고 B이므로 C' 꼴이 아닙니다"))
            kept.append(u)
            continue

        uid = u.get("id")
        why = f"함의로 분류됐지만 {', '.join(reasons)}. 프로그램이 단위에서 질문으로 옮김 (원래 단위는 draft_unit)"
        target = next((q for q in questions if uid is not None and uid in (q.get("related_units") or [])), None)
        if target is not None:
            target["draft_unit"] = copy.deepcopy(u)
            fixes.append(Issue("fix", _where(u, "단위"), f"{why}. 같은 내용의 질문 {target.get('id')}에 붙임"))
        else:
            qid = f"Q-{scope}-{next_no:02d}"
            next_no += 1
            questions.append({
                "id": qid, "key": None, "topic": "근거가 약한 함의",
                "question": f"{u.get('when') or ''} → {u.get('then') or ''} 동작이 필요한가요?".strip(" →"),
                "why": why, "priority": "하", "related_units": [], "draft_unit": copy.deepcopy(u),
            })
            fixes.append(Issue("fix", _where(u, "단위"), f"{why}. 질문 {qid}로 옮김"))
        for q in questions:                       # 없어진 단위를 가리키지 않게
            if uid is not None and uid in (q.get("related_units") or []):
                q["related_units"] = [r for r in q["related_units"] if r != uid]
    return kept, questions, fixes


def tag_missing_markers(units: list[dict], missing: set[str], screen_id: str) -> list[Issue]:
    """입력 점검에서 그림에 마커가 없던 항목(예: 그림이 잘림)을 근거로 한 단위에 issue를 붙인다.
    모델이 실행마다 이 표시를 빠뜨릴 수 있어서 프로그램이 같은 기준으로 붙인다."""
    fixes: list[Issue] = []
    if not missing:
        return fixes
    for u in units:
        if not isinstance(u, dict):
            continue
        hit = sorted(covered_items({"units": [u]}, screen_id) & missing)
        if not hit:
            continue
        note = f"입력 점검: 그림에서 {', '.join(hit)}의 마커를 찾지 못함 (그림이 잘렸을 수 있음)"
        issue = str(u.get("issue") or "")
        if "입력 점검" in issue:
            continue
        u["issue"] = f"{issue} / {note}" if issue else note
        fixes.append(Issue("fix", _where(u, "단위"), note))
    return fixes


# ---------- ③ 정합성 판정 ----------

JUDGE_STATUSES = ["구현", "불일치", "미구현", "확인필요"]
JUDGE_FIELDS = ["unit_id", "status", "mismatch", "evidence", "note"]


def validate_judge(obj: dict, screen_id: str, unit_ids: list[str]) -> list[Issue]:
    out: list[Issue] = []
    if not isinstance(obj.get("results"), list):
        return [Issue("error", screen_id, "results가 목록이 아닙니다")]
    if not isinstance(obj.get("extras", []), list):
        out.append(Issue("error", screen_id, "extras가 목록이 아닙니다"))
    seen = set()
    for r in obj["results"]:
        where = str(r.get("unit_id")) if isinstance(r, dict) else "(결과 아님)"
        if not isinstance(r, dict):
            out.append(Issue("error", where, "결과가 객체가 아닙니다"))
            continue
        missing = [f for f in JUDGE_FIELDS if f not in r]
        if missing:
            out.append(Issue("error", where, f"필드 누락: {', '.join(missing)}"))
        if r.get("unit_id") not in unit_ids:
            out.append(Issue("error", where, "받은 단위 목록에 없는 unit_id입니다"))
        if r.get("status") not in JUDGE_STATUSES:
            out.append(Issue("error", where, f"status는 {'/'.join(JUDGE_STATUSES)} 중 하나여야 합니다"))
        if not isinstance(r.get("evidence", []), list) or not isinstance(r.get("mismatch", []), list):
            out.append(Issue("error", where, "evidence와 mismatch는 목록이어야 합니다"))
        elif r.get("status") in ("구현", "불일치") and not r.get("evidence"):
            out.append(Issue("error", where, "구현·불일치 판정에는 근거 코드가 있어야 합니다"))
        seen.add(r.get("unit_id"))
    missing_units = [u for u in unit_ids if u not in seen]
    if missing_units:
        out.append(Issue("error", screen_id, f"판정이 빠진 단위: {', '.join(missing_units)}"))
    return out


_SEVERITY = {"구현": 0, "확인필요": 1, "불일치": 2, "미구현": 3}


def item_keys(unit: dict) -> list[str]:
    """단위의 source를 기획서 항목 이름으로 바꾼다. 예: "Description 2-(1)" → "LOGIN-001 Description 2"."""
    sid = unit.get("screen_id", "")
    keys = []
    for s in unit.get("source", []) or []:
        s = str(s)
        prefix = sid
        m_screen = SCREEN_PREFIX.match(s.strip())
        if m_screen:
            prefix, s = m_screen.group(1), m_screen.group(2)
        found = [f"Description {int(n)}" for n in SOURCE_DESC.findall(s)] + [f"Action {a}" for a in SOURCE_ACTION.findall(s)]
        keys += [f"{prefix} {f}" for f in found] or [f"{prefix} {s}"]
    return list(dict.fromkeys(keys))


def aggregate_items(units: list[dict], verdicts: dict[str, str]) -> dict[str, dict]:
    """같은 기획서 항목에서 나온 단위들의 판정을 모은다. 섞여 있으면 부분구현."""
    groups: dict[str, list[str]] = {}
    for u in units:
        if u.get("id") in verdicts:
            for k in item_keys(u):
                groups.setdefault(k, []).append(u["id"])
    out = {}
    for k, ids in groups.items():
        statuses = {verdicts[i] for i in ids}
        status = statuses.pop() if len(statuses) == 1 else "부분구현"
        out[k] = {"status": status, "units": ids}
    return out


def merge_candidates(units: list[dict], results: dict[str, dict]) -> list[dict]:
    """너무 잘게 쪼갠 신호: 같은 화면에서 행동(when)·판정·근거 줄이 모두 같은 단위 쌍."""
    def sig(u):
        r = results.get(u.get("id"), {})
        ev = tuple(sorted(f"{e.get('file')}:{e.get('line')}" for e in r.get("evidence", []) if isinstance(e, dict)))
        return (u.get("screen_id"), _norm_text(u.get("when")), r.get("status"), ev)

    buckets: dict[tuple, list[str]] = {}
    for u in units:
        s = sig(u)
        if u.get("id") in results and s[3]:          # 근거가 있는 경우만 (빈 근거끼리는 비교 의미 없음)
            buckets.setdefault(s, []).append(u["id"])
    return [{"units": ids, "reason": "행동·판정·근거 코드 줄이 모두 같음"} for ids in buckets.values() if len(ids) > 1]


def _norm_text(v) -> str:
    return re.sub(r"\s+", "", str(v or ""))


def worst_status(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: _SEVERITY.get(s, 1)) if statuses else "확인필요"
