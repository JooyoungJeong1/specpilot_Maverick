"""시연용 로컬 서버: 웹(frontend)에서 올린 기획서 PDF와 소스 코드로 백엔드를 끝까지 돌린다.

    python -m specpilot serve          (기본 http://127.0.0.1:8765. 웹 개발 서버가 /api를 이리로 넘긴다)

주소와 형식은 프론트가 정해 둔 것을 따른다 (frontend/src/api/api.ts, src/types/progress.ts).
    GET  /api/health          서버가 켜져 있는지, 지금 돌고 있는 작업
    POST /api/analyses        multipart: name, plans(PDF, 여러 개면 이어 붙임), code(zip) 또는 repoUrl → {"jobId"}
    GET  /api/analyses/{id}   진행 상태(Progress). 실행 폴더에 단계마다 남는 파일(meta)로 만든다

실행은 명령어와 똑같이 run(입력 점검 → ① → 게이트 → ②) → judge(③, 코드가 있으면) → scenario(④)를
차례로 부른다(따로 프로세스). 그래서 웹으로 돌린 결과도 명령어로 돌린 결과와 같은 실행 폴더가 된다.
- 결과: output/demo-<날짜-시각>/  (job.json: 작업 상태, server.log: 단계별 출력)
- 올린 파일: output/_uploads/<실행ID>/  (기업 자료라 git에 올라가지 않는다. output/은 .gitignore)
한 번에 하나만 돌린다. 진행 중에 또 올리면 409.
"""
# FastAPI가 처리 함수의 타입(UploadFile 등)을 실행 중에 읽어야 해서 from __future__ import annotations를 쓰지 않는다
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .stages import read_json, write_json

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
UPLOADS = "_uploads"
JOB_FILE = "job.json"
LOG_FILE = "server.log"
JOB_ID = re.compile(r"^demo-[0-9]{8}-[0-9]{6}(-[0-9]+)?$")
FINAL = {"완료", "확인필요", "실패", "반려"}
JUDGE_FINAL = {"완료", "확인필요", "실패"}
STEPS = ["prepare", "run", "judge", "scenario", "done"]
STEP_OF = {"code_facts": "judge"}        # 코드 분석은 ③ 단계의 앞부분으로 보여 준다
MAX_ZIP_FILES = 50_000
MAX_ZIP_BYTES = 1024 * 1024 * 1024       # 압축을 푼 크기 1GB


@dataclass
class ServeOptions:
    output_dir: Path
    workers: int = 2              # ② 동시 호출 수
    code_facts: bool = False      # ③ 전에 code_analysis를 돌려 --facts로 넣는다


class InputError(ValueError):
    """올린 파일이 잘못됨 (400으로 돌려준다)"""


# ---------- 작업 저장 ----------

class Jobs:
    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.lock = threading.Lock()
        self.active: str | None = None

    def run_dir(self, job_id: str) -> Path:
        return self.output_dir / job_id

    def upload_dir(self, job_id: str) -> Path:
        return self.output_dir / UPLOADS / job_id

    def load(self, job_id: str) -> dict | None:
        if not JOB_ID.match(job_id or ""):
            return None
        p = self.run_dir(job_id) / JOB_FILE
        return read_json(p) if p.exists() else None

    def save(self, job: dict) -> None:
        write_json(self.run_dir(job["jobId"]) / JOB_FILE, job)

    def new_id(self) -> str:
        base = f"demo-{datetime.now():%Y%m%d-%H%M%S}"
        job_id, n = base, 2
        while self.run_dir(job_id).exists():
            job_id, n = f"{base}-{n}", n + 1
        return job_id

    def recover(self) -> None:
        """서버가 꺼졌다 켜지면 돌던 작업은 이어 갈 수 없으므로 실패로 적어 둔다."""
        if not self.output_dir.exists():
            return
        for p in self.output_dir.glob(f"demo-*/{JOB_FILE}"):
            job = read_json(p)
            if job.get("state") == "running":
                job.update(state="failed", message="서버가 다시 시작돼 분석이 중단됐습니다. 다시 올려 주세요.",
                           finished_at=_now())
                write_json(p, job)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- 올린 파일 준비 ----------

def merge_plans(pdfs: list[Path], dest: Path) -> Path:
    """기획 문서 PDF가 여러 개면 올린 순서대로 이어 붙여 하나로 만든다 (백엔드는 PDF 하나를 받는다)."""
    for p in pdfs:
        with open(p, "rb") as f:
            if f.read(5) != b"%PDF-":
                raise InputError(f"PDF 파일이 아닙니다: {p.name}")
    if len(pdfs) == 1:
        shutil.copyfile(pdfs[0], dest)
        return dest
    from pypdf import PdfWriter
    writer = PdfWriter()
    for p in pdfs:
        writer.append(str(p))
    with open(dest, "wb") as f:
        writer.write(f)
    return dest


def extract_zip(zip_path: Path, dest: Path) -> Path:
    """소스 코드 zip을 푼다. 폴더 밖으로 나가는 경로는 막는다. 맨 위 폴더가 하나뿐이면 그 안을 코드 폴더로 쓴다."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise InputError("소스 코드 파일이 zip 압축 파일이 아닙니다")
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_FILES or sum(i.file_size for i in infos) > MAX_ZIP_BYTES:
            raise InputError("소스 코드 zip이 너무 큽니다")
        dest.mkdir(parents=True, exist_ok=True)
        root = dest.resolve()
        for info in infos:
            name = info.filename.replace("\\", "/")
            target = (dest / name).resolve()
            if not str(target).startswith(str(root) + os.sep) and target != root:
                continue                                   # ../ 나 절대 경로
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    entries = [p for p in dest.iterdir() if p.name != "__MACOSX"]
    return entries[0] if len(entries) == 1 and entries[0].is_dir() else dest


def clone_repo(url: str, dest: Path, log) -> Path:
    """저장소 주소면 git으로 받는다. 비공개 저장소라 로그인을 물으면 기다리지 않고 실패한다."""
    if not re.match(r"^https://[\w.-]+/[\w./~-]+$", url):
        raise InputError("저장소 주소는 https://로 시작해야 합니다")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], stdout=log, stderr=subprocess.STDOUT,
                          env=env, timeout=600)
    if proc.returncode != 0:
        raise InputError("저장소를 받지 못했습니다. 주소를 확인하거나 zip으로 올려 주세요")
    return dest


# ---------- 실행 ----------

def _execute(args: list[str], log, cwd: Path = BACKEND_DIR, module: str = "specpilot", env: dict | None = None) -> int:
    """백엔드 명령 하나를 따로 프로세스로 돌린다. 출력은 server.log에 남는다."""
    proc = subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                          env=env)
    return proc.returncode


def _child_env(options: ServeOptions) -> dict:
    return {**os.environ, "SPECPILOT_OUTPUT_DIR": str(options.output_dir), "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1"}


def _tail(path: Path, n: int = 3) -> str:
    try:
        lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    except OSError:
        return ""
    return " / ".join(l for l in lines[-n:] if not l.startswith("==="))


def run_pipeline(job: dict, jobs: Jobs, options: ServeOptions, execute=_execute) -> None:
    """올린 파일 준비 → run → judge → scenario. 단계가 바뀔 때마다 job.json을 고친다."""
    run_dir = jobs.run_dir(job["jobId"])
    up = jobs.upload_dir(job["jobId"])
    env = _child_env(options)

    def finish(state: str, message: str | None = None) -> None:
        job.update(state=state, message=message, finished_at=_now())
        if state == "done":
            job["step"] = "done"
        jobs.save(job)

    def step(name: str, args: list[str], **kw) -> int:
        job["step"] = name
        jobs.save(job)
        log.write(f"\n=== {name}: {' '.join(args)}\n")
        log.flush()
        rc = execute(args, log, env=env, **kw)
        log.flush()
        return rc

    with open(run_dir / LOG_FILE, "a", encoding="utf-8") as log:
        try:
            plan = merge_plans([up / "plans" / n for n in job["plans"]], up / "plan.pdf")
            if job.get("repo_url"):
                code_root = clone_repo(job["repo_url"], up / "code", log)
            elif job.get("code_zip"):
                code_root = extract_zip(up / job["code_zip"], up / "code")
            else:
                code_root = None
            job["code_root"] = str(code_root) if code_root else None

            rc = step("run", ["run", "--pdf", str(plan), "--name", job["jobId"], "--workers", str(options.workers)])
            if rc == 3:
                return finish("rejected", _reject_reason(run_dir) or "기획서를 읽을 수 없어 반려했습니다.")
            if rc != 0:
                return finish("failed", f"② 요구사항 추출에서 멈췄습니다. {_tail(run_dir / LOG_FILE)}")

            if code_root:
                facts = []
                if options.code_facts:
                    facts = _code_facts(job, run_dir, code_root, log, step)
                rc = step("judge", ["judge", "--run", str(run_dir), "--code", str(code_root), *facts])
                if rc != 0:
                    return finish("failed", f"③ 코드 비교에서 멈췄습니다. {_tail(run_dir / LOG_FILE)}")

            project = job.get("name") or job["jobId"]
            rc = step("scenario", ["scenario", "--run", str(run_dir), "--project", project])
            if rc != 0:
                return finish("failed", f"④ 사양서 작성에서 멈췄습니다. {_tail(run_dir / LOG_FILE)}")
            finish("done")
        except InputError as e:
            finish("failed", str(e))
        except Exception as e:                       # 예상 못 한 오류도 진행 화면에 보이게
            log.write(f"\n[서버 오류] {type(e).__name__}: {e}\n")
            finish("failed", f"서버 오류: {e}")
        finally:
            jobs.active = None


def _code_facts(job: dict, run_dir: Path, code_root: Path, log, step) -> list[str]:
    """code_analysis(자바 파서 등)가 있으면 코드 분석 사실을 만들어 ③에 넣는다. 실패해도 ③은 그대로 돈다."""
    if not (REPO_DIR / "code_analysis" / "__main__.py").exists():
        log.write("\n[코드 분석] code_analysis 폴더가 없어 건너뜀\n")
        return []
    out = run_dir / "code_facts.json"
    rc = step("code_facts", ["--code", str(code_root), "--requirements", str(run_dir / "requirements.json"),
                             "--out", str(out)], cwd=REPO_DIR, module="code_analysis")
    job["step"] = "judge"
    if rc != 0 or not out.exists():
        log.write("\n[코드 분석] 실패해서 코드 분석 사실 없이 ③을 돈다\n")
        return []
    return ["--facts", str(out)]


def _reject_reason(run_dir: Path) -> str | None:
    for name in ("preflight.json", "gate.json"):
        p = run_dir / name
        if p.exists():
            reasons = read_json(p).get("reasons") or []
            if reasons:
                return "기획서를 반려했습니다: " + "; ".join(reasons[:3])
    return None


# ---------- 진행 상태 ----------

def _read(p: Path):
    try:
        return read_json(p) if p.exists() else None
    except (OSError, ValueError):            # 쓰는 중인 파일
        return None


def _metas(folder: Path, skip: tuple[str, ...] = ()) -> dict[str, dict]:
    if not folder.exists():
        return {}
    out = {}
    for p in folder.glob("*.meta.json"):
        if p.name in skip:
            continue
        m = _read(p)
        if isinstance(m, dict):
            out[p.name[: -len(".meta.json")]] = m
    return out


def build_progress(job: dict, run_dir: Path, workers: int = 1) -> dict:
    """프론트의 Progress 모양(frontend/src/types/progress.ts)으로 진행 상태를 만든다."""
    from .judge import units_by_screen
    from .scenario import build_groups

    state = job.get("state", "running")
    step = STEP_OF.get(job.get("step"), job.get("step") or "prepare")
    at = STEPS.index(step) if step in STEPS else 0
    running = state == "running"
    failed_at = step if state in ("failed", "rejected") else None
    has_code = bool(job.get("code_zip") or job.get("repo_url"))

    pre = _read(run_dir / "preflight.json")
    prof = _read(run_dir / "app_profile.json")
    req = _read(run_dir / "requirements.json")
    screens = [s for s in (prof or {}).get("screens", []) if isinstance(s, dict) and s.get("screen_id")]
    smeta = _metas(run_dir / "screens")
    jmeta = _metas(run_dir / "judge", skip=("code_map.meta.json",))
    scmeta = _metas(run_dir / "scenario")

    def stage(key, done_flag, active, failed, done, total):
        st = "failed" if failed else "done" if done_flag else "running" if active and running else "waiting"
        return {"key": key, "state": st, "done": done, "total": total}

    pre_rejected = bool(pre) and pre.get("verdict") == "반려"
    stages = [stage("preflight", pre is not None and not pre_rejected, at == 1,
                    failed_at == "run" and (pre_rejected or pre is None), int(pre is not None), 1),
              stage("profile", prof is not None, at == 1 and pre is not None,
                    failed_at == "run" and pre is not None and not pre_rejected and prof is None, int(prof is not None), 1)]
    finished = sum(1 for s in screens if (smeta.get(s["screen_id"]) or {}).get("status") in FINAL)
    stages.append(stage("decompose", req is not None, at == 1 and prof is not None,
                        failed_at == "run" and prof is not None and req is None,
                        len(screens) if req is not None else finished, len(screens)))

    judge_order = list(units_by_screen(req).keys()) if req and has_code else []
    if has_code:
        jdone = sum(1 for k in judge_order if (jmeta.get(k) or {}).get("status") in JUDGE_FINAL)
        jfin = (run_dir / "judge_report.json").exists() and at > STEPS.index("judge")
        stages.append(stage("judge", jfin, at == 2, failed_at == "judge",
                            len(judge_order) if jfin else jdone, len(judge_order)))
    else:
        stages.append({"key": "judge", "state": "skipped", "done": 0, "total": 0})

    groups = build_groups(req)[0] if req else []
    sfin = (run_dir / "scenario_report.json").exists() and step == "done"
    sdone = sum(1 for g in groups if (scmeta.get(g["id"]) or {}).get("status") in FINAL)
    stages.append(stage("scenario", sfin, at == 3, failed_at == "scenario", len(groups) if sfin else sdone, len(groups)))

    # 화면별 표: ②는 아직 결과가 없는 화면 앞쪽 workers개가 진행 중, ③은 아직 결과가 없는 첫 화면이 진행 중
    pending = [s["screen_id"] for s in screens if (smeta.get(s["screen_id"]) or {}).get("status") not in FINAL]
    dec_running = set(pending[:max(1, workers)]) if running and at == 1 and prof is not None and req is None else set()
    jpending = [k for k in judge_order if (jmeta.get(k) or {}).get("status") not in JUDGE_FINAL]
    judge_running = set(jpending[:1]) if running and at == 2 else set()
    status_by = (req or {}).get("screen_status") or {}
    rejected = (req or {}).get("rejected_screens") or {}
    rows = []
    for s in screens:
        sid = s["screen_id"]
        m = smeta.get(sid) or {}
        dec = m.get("status") if m.get("status") in FINAL else ("진행 중" if sid in dec_running else "대기")
        units = None
        if dec in FINAL and dec != "반려":
            units = (status_by.get(sid) or {}).get("units")
            if units is None:
                units = len((_read(run_dir / "screens" / f"{sid}.json") or {}).get("units") or [])
        if not has_code or dec == "반려" or (req is not None and sid not in judge_order):
            judge = None                                   # 코드와 비교하지 않는 화면
        elif (jmeta.get(sid) or {}).get("status") in JUDGE_FINAL:
            judge = jmeta[sid]["status"]
        else:
            judge = "진행 중" if sid in judge_running else "대기"
        rows.append({"screenId": sid, "name": s.get("name") or "", "decompose": dec, "units": units,
                     "rejectReason": m.get("reject_reason") or rejected.get(sid), "judge": judge})

    problems = None
    if state == "done":
        report = _read(run_dir / "judge_report.json")
        by = ((report or {}).get("summary") or {}).get("by_status") or {}
        problems = sum(by.get(k, 0) for k in ("미구현", "불일치", "확인필요")) if report else None
    return {
        "jobId": job["jobId"], "name": job.get("name") or "", "state": state, "stages": stages, "screens": rows,
        "runId": job["jobId"] if state == "done" else None, "problems": problems, "message": job.get("message"),
    }


# ---------- 웹 서버 ----------

def create_app(options: ServeOptions, execute=_execute, background: bool = True):
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile

    jobs = Jobs(options.output_dir)
    jobs.recover()
    app = FastAPI(title="SpecPilot 시연 서버")
    app.state.jobs = jobs

    @app.get("/api/health")
    def health():
        return {"ok": True, "running": jobs.active}

    @app.post("/api/analyses")
    def start(name: str = Form(""), plans: list[UploadFile] = File(...), code: UploadFile | None = File(None),
              repoUrl: str | None = Form(None)):
        pdfs = [f for f in plans if f.filename]
        if not pdfs:
            raise HTTPException(400, "기획 문서(PDF)를 올려 주세요")
        if code is None and not (repoUrl or "").strip():
            raise HTTPException(400, "소스 코드 zip이나 저장소 주소를 넣어 주세요")
        with jobs.lock:
            if jobs.active:
                raise HTTPException(409, f"다른 분석이 진행 중입니다 ({jobs.active}). 끝난 뒤 다시 올려 주세요")
            job_id = jobs.new_id()
            jobs.active = job_id
        try:
            up = jobs.upload_dir(job_id)
            (up / "plans").mkdir(parents=True, exist_ok=True)
            names = []
            for i, f in enumerate(pdfs, 1):
                fname = f"{i:02d}-{_safe_name(f.filename)}"
                with open(up / "plans" / fname, "wb") as out:
                    shutil.copyfileobj(f.file, out)
                with open(up / "plans" / fname, "rb") as check:
                    if check.read(5) != b"%PDF-":
                        raise HTTPException(400, f"PDF 파일이 아닙니다: {f.filename}")
                names.append(fname)
            code_zip = None
            if code is not None and code.filename:
                code_zip = "code.zip"
                with open(up / code_zip, "wb") as out:
                    shutil.copyfileobj(code.file, out)
            jobs.run_dir(job_id).mkdir(parents=True, exist_ok=True)
            job = {"jobId": job_id, "name": (name or "").strip() or job_id, "state": "running", "step": "prepare",
                   "plans": names, "code_zip": code_zip, "repo_url": None if code_zip else (repoUrl or "").strip() or None,
                   "code_root": None, "created_at": _now(), "finished_at": None, "message": None}
            jobs.save(job)
        except Exception:
            jobs.active = None
            shutil.rmtree(jobs.upload_dir(job_id), ignore_errors=True)
            raise
        if background:
            threading.Thread(target=run_pipeline, args=(job, jobs, options, execute), daemon=True).start()
        else:
            run_pipeline(job, jobs, options, execute)
        return {"jobId": job_id}

    @app.get("/api/analyses/{job_id}")
    def progress(job_id: str):
        job = jobs.load(job_id)
        if job is None:
            raise HTTPException(404, "작업이 없습니다")
        return build_progress(job, jobs.run_dir(job_id), options.workers)

    return app


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)[:120] or "plan.pdf"


def serve(host: str, port: int, options: ServeOptions) -> int:
    try:
        import uvicorn
        app = create_app(options)
    except ImportError as e:
        print(f"서버 패키지가 없습니다 ({e}). backend 폴더에서 pip install -r requirements.txt", file=sys.stderr)
        return 2
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[경고] ANTHROPIC_API_KEY가 없습니다. .env를 확인하세요 (분석을 시작하면 ①에서 멈춥니다)", file=sys.stderr)
    print(f"[시연 서버] http://{host}:{port}  결과: {options.output_dir}  (끄려면 Ctrl+C)")
    print("  웹은 frontend 폴더에서 npm run dev 로 켠다. 웹의 /api 요청이 이 서버로 온다.")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
