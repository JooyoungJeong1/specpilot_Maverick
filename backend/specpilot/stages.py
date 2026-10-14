"""① 앱 프로필과 ② 화면별 분해 실행. 검사에 걸리면 문제를 알려 주고 다시 부른다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import pdf_utils, preflight, schema
from .config import Settings
from .llm import LLM, JSONParseError, parse_json
from .prompts import PromptSet, RenderedPrompt

STATUS_DONE = "완료"
STATUS_REVIEW = "확인필요"   # 결과는 있지만 검사를 다 통과하지 못함
STATUS_FAILED = "실패"       # 쓸 수 있는 결과가 없음
STATUS_REJECTED = "반려"     # 입력 점검(게이트)이나 ②가 화면을 읽을 수 없다고 판단함
STATUS_DRY = "dry-run"


class StageFailed(RuntimeError):
    pass


@dataclass
class RunContext:
    run_dir: Path
    pdf_path: Path
    settings: Settings
    prompts: PromptSet
    llm: LLM | None          # None이면 dry-run (프롬프트만 파일로 남김)
    _texts: pdf_utils.TextIndex | None = field(default=None, repr=False)
    _preflight: dict | None = field(default=None, repr=False)

    @property
    def dry_run(self) -> bool:
        return self.llm is None

    @property
    def texts(self) -> pdf_utils.TextIndex:
        """설계서 원문 (quote 대조용). 처음 쓸 때 한 번 읽는다."""
        if self._texts is None:
            self._texts = pdf_utils.TextIndex(self.pdf_path)
        return self._texts

    @property
    def gate(self) -> dict | None:
        """게이트 판정 결과 (gate.json). 없으면 None."""
        p = self.run_dir / "gate.json"
        return read_json(p) if p.exists() else None

    @property
    def preflight(self) -> dict | None:
        """입력 점검 결과 (preflight.json). 없으면 None."""
        if self._preflight is None:
            p = self.run_dir / "preflight.json"
            if p.exists():
                self._preflight = read_json(p)
        return self._preflight

    def path(self, *parts: str) -> Path:
        p = self.run_dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _feedback(issues: list[schema.Issue]) -> str:
    lines = [f"- [{i.where}] {i.message}" for i in schema.errors(issues)[:30]]
    return ("직전 출력에 아래 문제가 있다. 지침을 다시 확인하고, 문제를 고친 JSON 하나만 다시 출력한다. "
            "문제가 없는 부분은 바꾸지 않는다.\n" + "\n".join(lines))


def _add_usage(total: dict, usage: dict) -> None:
    for k, v in usage.items():
        total[k] = total.get(k, 0) + (v or 0)


def _call_with_retry(ctx: RunContext, name: str, rendered: RenderedPrompt, content: list[dict],
                     validate, prepare=None) -> tuple[dict | None, list[schema.Issue], dict]:
    """호출 → 파싱 → (prepare: 프로그램이 채울 것 채우기) → 검사. error가 있으면 문제 목록을 붙여 다시 부른다.

    반환: (마지막으로 파싱된 결과 또는 None, 마지막 검사 결과, 메타)
    """
    messages = [{"role": "user", "content": content}]
    usage: dict = {}
    obj, issues = None, []
    attempts = 0
    retry_reasons: list[dict] = []   # 시도마다 걸린 오류. 재시도 끝에 통과해도 왜 다시 불렀는지 남긴다
    for attempt in range(1, ctx.settings.max_retries + 2):
        attempts = attempt
        result = ctx.llm.complete(rendered.system, messages, ctx.settings.max_tokens)
        _add_usage(usage, result.usage)
        ctx.path("raw", f"{name}.attempt{attempt}.txt").write_text(result.text, encoding="utf-8")

        if result.stop_reason == "max_tokens":
            th = (result.usage or {}).get("thinking_tokens", 0)
            issues = [schema.Issue("error", name,
                                   f"출력이 길이 한도에서 잘렸습니다 (출력 {len(result.text)}자, 생각 토큰 {th}). "
                                   "SPECPILOT_MAX_TOKENS를 늘리거나 SPECPILOT_EFFORT를 낮추세요")]
            break  # 다시 불러도 같은 길이에서 잘리므로 재시도하지 않는다
        try:
            obj = parse_json(result.text)
        except JSONParseError as e:
            obj, issues = None, [schema.Issue("error", name, str(e))]
        else:
            if prepare:
                prepare(obj)
            issues = validate(obj)
        if not schema.errors(issues):
            break
        retry_reasons.append({"attempt": attempt, "errors": [f"[{i.where}] {i.message}" for i in schema.errors(issues)]})
        messages = messages + [
            {"role": "assistant", "content": result.text},
            {"role": "user", "content": _feedback(issues)},
        ]
    meta = {"attempts": attempts, "retry_reasons": retry_reasons, "usage": usage,
            "prompt_version": rendered.version, "model": ctx.settings.model,
            "thinking": ctx.settings.thinking, "effort": ctx.settings.effort,
            "max_tokens": ctx.settings.max_tokens, "text_extractor": pdf_utils.text_extractor()}
    return obj, issues, meta


def _write_preview(ctx: RunContext, name: str, rendered: RenderedPrompt, attachment: str) -> None:
    text = (f"=== system (고정 부분, 캐시) / version {rendered.version} ===\n{rendered.system}\n\n"
            f"=== 첨부 ===\n{attachment}\n\n=== user (입력 부분) ===\n{rendered.user_input}\n")
    ctx.path("prompts_preview", f"{name}.txt").write_text(text, encoding="utf-8")


# ---------- ① 앱 프로필 ----------

def run_app_profile(ctx: RunContext) -> dict:
    rendered = ctx.prompts.render("app_profile")
    if ctx.dry_run:
        _write_preview(ctx, "app_profile", rendered, "PDF 전체")
        raise StageFailed("dry-run: ①은 호출하지 않았습니다. ②까지 미리보려면 --app-profile로 기존 결과를 주세요")

    total = pdf_utils.page_count(ctx.pdf_path)
    content = [pdf_utils.document_block(ctx.pdf_path.read_bytes()), {"type": "text", "text": rendered.user_input}]
    prep_fixes: list[schema.Issue] = []

    def prepare(o):
        prep_fixes[:] = schema.normalize_app_profile(o)

    obj, issues, meta = _call_with_retry(
        ctx, "app_profile", rendered, content,
        lambda o: schema.validate_app_profile(o, total, ctx.texts, ctx.settings.quote_strict), prepare)

    # 화면 목록 같은 프로필 자체의 오류는 멈출 사유다 (뒤 단계가 모두 화면 목록을 기준으로 돈다).
    # 앱 전체 단위·질문 하나의 오류(형식, 원문에 없는 quote)는 그 항목만 rejected로 빼고 진행한다.
    item_keys = {x.get("key") for x in (obj or {}).get("units", []) or [] if isinstance(x, dict)} | \
                {x.get("key") for x in (obj or {}).get("questions", []) or [] if isinstance(x, dict)}
    blocking = [i for i in schema.errors(issues) if i.where not in item_keys]
    if obj is None or blocking:
        meta.update(status=STATUS_FAILED, issues=[i.to_dict() for i in issues])
        write_json(ctx.path("app_profile.meta.json"), meta)
        raise StageFailed("① 앱 프로필이 검사를 통과하지 못했습니다. raw/ 와 app_profile.meta.json을 확인하세요")
    status = STATUS_DONE
    if schema.errors(issues):
        status = STATUS_REVIEW
        obj = _split_invalid(obj, "APP", ctx, None)
        obj.pop("skipped", None)

    units, questions = schema.assign_ids(obj.get("units") or [], obj.get("questions") or [], "APP")
    units, questions, fixes = schema.gate_implied(units, questions, "APP", ctx.texts)
    obj["units"], obj["questions"] = units, questions
    issues += prep_fixes + fixes
    meta.update(status=status, issues=[i.to_dict() for i in issues])
    write_json(ctx.path("app_profile.json"), obj)
    write_json(ctx.path("app_profile.meta.json"), meta)
    return obj


# ---------- ② 화면별 분해 ----------

def screen_pages(screen: dict) -> list[int]:
    return sorted(set(screen.get("pages", [])) | set(screen.get("state_pages", []) or []))


def expected_items_for(ctx: RunContext, screen: dict) -> tuple[set[str], str]:
    """그 화면 페이지의 기획서 항목 번호(누락 검사의 기준)와 어디서 얻었는지.
    입력 점검(preflight.json)이 있으면 그 결과를 쓰고, 없으면 그 자리에서 찾는다."""
    found = preflight.checklist(ctx.preflight, screen.get("pages", []))
    if found is not None:
        return found, f"입력 점검 ({ctx.preflight.get('extractor')})"
    return pdf_utils.expected_items(ctx.pdf_path, screen.get("pages", [])), f"배치 글자 ({pdf_utils.text_extractor()})"


def _split_invalid(obj: dict, sid: str, ctx: RunContext, pages: list[int] | None) -> dict:
    """검사를 끝내 통과하지 못한 단위·질문을 결과에서 빼되 버리지 않고 rejected에 남긴다."""
    good_u, bad_u, good_q, bad_q = [], [], [], []
    for u in obj.get("units") or []:
        errs = schema.errors(schema.check_unit(u, sid)
                             + schema.check_quotes([u] if isinstance(u, dict) else [], ctx.texts, pages,
                                                   ctx.settings.quote_strict))
        (bad_u if errs else good_u).append({"unit": u, "errors": [e.message for e in errs]} if errs else u)
    for q in obj.get("questions") or []:
        errs = schema.errors(schema.check_question(q, sid))
        (bad_q if errs else good_q).append({"question": q, "errors": [e.message for e in errs]} if errs else q)
    obj["units"], obj["questions"] = good_u, good_q
    obj["rejected"] = {"units": bad_u, "questions": bad_q}
    obj.setdefault("skipped", [])
    return obj


def run_screen(ctx: RunContext, screen: dict, profile: dict) -> dict:
    sid = screen["screen_id"]
    pages = screen_pages(screen)
    rendered = ctx.prompts.render(
        "screen_decompose",
        APP_PROFILE=json.dumps(profile, ensure_ascii=False),
        SCREEN_ID=sid,
        SCREEN_PAGES=", ".join(f"p.{p}" for p in pages),
    )
    if ctx.settings.send_full_pdf:
        pdf_bytes, attachment = ctx.pdf_path.read_bytes(), "PDF 전체"
    else:
        pdf_bytes, attachment = pdf_utils.subset_pdf(ctx.pdf_path, pages), f"원본 {pages} 페이지만 잘라 붙임"

    if ctx.dry_run:
        _write_preview(ctx, f"screen_{sid}", rendered, attachment)
        return {"screen_id": sid, "status": STATUS_DRY}

    expected, checklist_from = expected_items_for(ctx, screen)
    content = [pdf_utils.document_block(pdf_bytes), {"type": "text", "text": rendered.user_input}]
    obj, issues, meta = _call_with_retry(
        ctx, f"screen_{sid}", rendered, content,
        lambda o: schema.validate_screen(o, sid, expected, ctx.settings.coverage_strict,
                                         ctx.texts, pages, ctx.settings.quote_strict))
    meta.update(screen_id=sid, pages=pages, expected_items=sorted(expected), checklist_from=checklist_from)

    if obj is None:
        status = STATUS_FAILED
    elif not schema._is_blank(obj.get("reject_reason")):
        # ②가 화면을 읽을 수 없다고 판단: 결과를 쓰지 않고 이유만 남긴다. 기획서를 고친 뒤 이 화면만 다시 돌린다.
        status = STATUS_REJECTED
        meta["reject_reason"] = obj["reject_reason"]
        obj["units"], obj["questions"] = [], []
        write_json(ctx.path("screens", f"{sid}.json"), obj)
    else:
        status = STATUS_REVIEW if schema.errors(issues) else STATUS_DONE
        if status == STATUS_REVIEW:
            obj = _split_invalid(obj, sid, ctx, pages)
        meta["items_seen"] = obj.get("items_seen")
        units, questions = schema.assign_ids(obj.get("units") or [], obj.get("questions") or [], sid)
        units, questions, fixes = schema.gate_implied(units, questions, sid, ctx.texts)
        g = ((ctx.gate or {}).get("screens") or {}).get(sid) or {}
        fixes += schema.tag_missing_markers(units, set(g.get("missing_in_picture", [])) | set(g.get("letters_missing", [])), sid)
        obj["units"], obj["questions"] = units, questions
        issues += fixes
        write_json(ctx.path("screens", f"{sid}.json"), obj)

    meta.update(status=status, issues=[i.to_dict() for i in issues])
    write_json(ctx.path("screens", f"{sid}.meta.json"), meta)
    return meta


def mark_rejected(ctx: RunContext, screen: dict, reasons: list[str]) -> dict:
    """게이트에서 반려된 화면: ②를 부르지 않고 이유만 기록한다."""
    sid = screen["screen_id"]
    meta = {"screen_id": sid, "status": STATUS_REJECTED, "attempts": 0, "reject_reason": "; ".join(reasons),
            "rejected_by": "게이트(입력 점검)", "issues": []}
    data = ctx.run_dir / "screens" / f"{sid}.json"
    if data.exists():                     # 예전 실행 결과가 남아 있으면 이번 반려와 섞이지 않게 치운다
        data.replace(data.with_suffix(".json.old"))
    write_json(ctx.path("screens", f"{sid}.meta.json"), meta)
    return meta
