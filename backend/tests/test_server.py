"""시연 서버 테스트 (API 키 필요 없음). 백엔드 명령 대신 결과 파일을 써 주는 가짜 실행기를 쓴다.

가상의 문의 게시판 앱(QNA)으로 확인한다. 실제 기획서·코드는 넣지 않는다.
"""
import io
import json
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfWriter  # noqa: E402

from specpilot.server import Jobs, ServeOptions, build_progress, create_app, extract_zip  # noqa: E402
from specpilot.stages import read_json, write_json  # noqa: E402

SCREENS = [{"screen_id": "QNA-001", "name": "문의 목록", "depth": "고객센터", "type": "화면"},
           {"screen_id": "QNA-002", "name": "문의 작성", "depth": "고객센터", "type": "화면"}]


def unit(uid, sid, kind="표시"):
    return {"id": uid, "screen_id": sid, "source": ["Description 1"], "quote": "q", "origin": "명시", "reason": None,
            "kind": kind, "given": None, "when": "w", "conditions": [], "then": "t",
            "exact": {"message": None, "values": [], "target": None}, "issue": None}


def pdf_bytes(pages=1) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(100, 100)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


class FakeBackend:
    """run / judge / scenario 대신 결과 파일을 써 준다. 받은 명령을 calls에 남긴다."""

    def __init__(self, output_dir, run_code=0):
        self.out = output_dir
        self.run_code = run_code
        self.calls = []

    def __call__(self, args, log, env=None, **kw):
        self.calls.append(args)
        cmd = args[0]
        if cmd == "run":
            rd = self.out / args[args.index("--name") + 1]
            if self.run_code == 3:
                write_json(rd / "preflight.json", {"verdict": "반려", "reasons": ["글자층이 없습니다 (스캔본)"]})
                return 3
            write_json(rd / "preflight.json", {"verdict": "통과", "reasons": []})
            write_json(rd / "app_profile.json", {"screens": SCREENS})
            units = [unit("REQ-QNA-001-01", "QNA-001"), unit("REQ-QNA-002-01", "QNA-002"),
                     unit("REQ-QNA-002-02", "QNA-002", kind="제약")]
            for s in SCREENS:
                write_json(rd / "screens" / f"{s['screen_id']}.meta.json", {"screen_id": s["screen_id"], "status": "완료"})
            write_json(rd / "requirements.json", {
                "app_profile": {"screens": SCREENS, "flows": []}, "units": units, "questions": [],
                "screen_status": {"QNA-001": {"status": "완료", "units": 1}, "QNA-002": {"status": "완료", "units": 2}},
                "rejected_screens": {}})
            return self.run_code
        rd = self.out.parent / args[args.index("--run") + 1] if not args[args.index("--run") + 1].startswith("/") \
            else __import__("pathlib").Path(args[args.index("--run") + 1])
        if cmd == "judge":
            for s in SCREENS:
                write_json(rd / "judge" / f"{s['screen_id']}.meta.json", {"screen_id": s["screen_id"], "status": "완료"})
            write_json(rd / "judge_report.json", {"summary": {"by_status": {"구현": 1, "미구현": 1, "불일치": 1}}})
            return 0
        if cmd == "scenario":
            for gid in ("QNA-001", "QNA-002"):
                write_json(rd / "scenario" / f"{gid}.meta.json", {"group_id": gid, "status": "완료"})
            write_json(rd / "scenario_report.json", {"summary": {}})
            return 0
        raise AssertionError(args)


@pytest.fixture
def out(tmp_path):
    return tmp_path / "output"


def client_for(out, backend):
    app = create_app(ServeOptions(out, workers=2), execute=backend, background=False)
    return TestClient(app), app.state.jobs


def test_upload_runs_whole_pipeline(out):
    backend = FakeBackend(out)
    client, _ = client_for(out, backend)
    assert client.get("/api/health").json() == {"ok": True, "running": None}
    res = client.post("/api/analyses", data={"name": "시연 프로젝트"},
                      files=[("plans", ("기획서.pdf", pdf_bytes(), "application/pdf")),
                             ("code", ("code.zip", zip_bytes({"shop-main/src/A.java": "class A {}"}), "application/zip"))])
    assert res.status_code == 200
    job_id = res.json()["jobId"]
    assert job_id.startswith("demo-")

    run, judge, scenario = backend.calls
    assert run[:2] == ["run", "--pdf"] and run[2].endswith("plan.pdf") and run[3:] == ["--name", job_id, "--workers", "2"]
    assert judge[0] == "judge" and judge[4].endswith("shop-main")        # zip의 맨 위 폴더 하나는 벗겨서 코드 폴더로
    assert scenario[-2:] == ["--project", "시연 프로젝트"]

    p = client.get(f"/api/analyses/{job_id}").json()
    assert p["state"] == "done" and p["runId"] == job_id and p["name"] == "시연 프로젝트"
    assert [(s["key"], s["state"], s["done"], s["total"]) for s in p["stages"]] == [
        ("preflight", "done", 1, 1), ("profile", "done", 1, 1), ("decompose", "done", 2, 2),
        ("judge", "done", 2, 2), ("scenario", "done", 2, 2)]
    assert p["screens"][1] == {"screenId": "QNA-002", "name": "문의 작성", "decompose": "완료", "units": 2,
                               "rejectReason": None, "judge": "완료"}
    assert p["problems"] == 2
    job = read_json(out / job_id / "job.json")
    assert job["state"] == "done" and (out / "_uploads" / job_id / "code" / "shop-main" / "src" / "A.java").exists()
    assert client.get("/api/health").json()["running"] is None


def test_several_pdfs_are_joined_into_one(out):
    backend = FakeBackend(out)
    client, _ = client_for(out, backend)
    job_id = client.post("/api/analyses", data={"name": "a", "repoUrl": ""},
                         files=[("plans", ("1.pdf", pdf_bytes(2), "application/pdf")),
                                ("plans", ("2.pdf", pdf_bytes(3), "application/pdf")),
                                ("code", ("c.zip", zip_bytes({"A.java": "x"}), "application/zip"))]).json()["jobId"]
    from pypdf import PdfReader
    assert len(PdfReader(str(out / "_uploads" / job_id / "plan.pdf")).pages) == 5


def test_rejected_plan_shows_reason(out):
    client, _ = client_for(out, FakeBackend(out, run_code=3))
    job_id = client.post("/api/analyses", data={"name": "x"},
                         files=[("plans", ("p.pdf", pdf_bytes(), "application/pdf")),
                                ("code", ("c.zip", zip_bytes({"A.java": "x"}), "application/zip"))]).json()["jobId"]
    p = client.get(f"/api/analyses/{job_id}").json()
    assert p["state"] == "rejected" and "스캔본" in p["message"] and p["runId"] is None
    assert p["stages"][0]["state"] == "failed"


def test_bad_inputs_are_refused(out):
    client, jobs = client_for(out, FakeBackend(out))
    pdf = ("plans", ("p.pdf", pdf_bytes(), "application/pdf"))
    assert client.post("/api/analyses", data={"name": "x"}, files=[pdf]).status_code == 400          # 코드 없음
    not_pdf = client.post("/api/analyses", data={"name": "x", "repoUrl": "https://github.com/a/b"},
                          files=[("plans", ("p.pdf", b"hello", "application/pdf"))])
    assert not_pdf.status_code == 400 and "PDF 파일이 아닙니다" in not_pdf.json()["detail"]
    assert jobs.active is None                                                                     # 실패해도 다음 작업을 받는다
    jobs.active = "demo-20261026-000000"
    busy = client.post("/api/analyses", data={"name": "x", "repoUrl": "https://github.com/a/b"}, files=[pdf])
    assert busy.status_code == 409
    assert client.get("/api/analyses/../../etc").status_code == 404


def test_progress_while_decomposing(out, tmp_path):
    rd = out / "demo-20261026-120000"
    write_json(rd / "preflight.json", {"verdict": "통과"})
    write_json(rd / "app_profile.json", {"screens": SCREENS + [{"screen_id": "QNA-003", "name": "문의 상세"}]})
    write_json(rd / "screens" / "QNA-001.meta.json", {"status": "완료"})
    write_json(rd / "screens" / "QNA-001.json", {"units": [1, 2, 3]})
    job = {"jobId": rd.name, "name": "n", "state": "running", "step": "run", "code_zip": "code.zip"}
    p = build_progress(job, rd, workers=1)
    assert [(s["key"], s["state"], s["done"], s["total"]) for s in p["stages"]] == [
        ("preflight", "done", 1, 1), ("profile", "done", 1, 1), ("decompose", "running", 1, 3),
        ("judge", "waiting", 0, 0), ("scenario", "waiting", 0, 0)]
    assert [(r["decompose"], r["units"], r["judge"]) for r in p["screens"]] == [
        ("완료", 3, "대기"), ("진행 중", None, "대기"), ("대기", None, "대기")]
    no_code = build_progress({**job, "code_zip": None}, rd)
    assert no_code["stages"][3]["state"] == "skipped" and no_code["screens"][0]["judge"] is None


def test_zip_cannot_write_outside(tmp_path):
    z = tmp_path / "evil.zip"
    z.write_bytes(zip_bytes({"../evil.txt": "x", "ok/A.java": "y"}))
    root = extract_zip(z, tmp_path / "code")
    assert not (tmp_path / "evil.txt").exists() and (root / "A.java").exists()


def test_running_job_is_marked_failed_after_restart(out):
    write_json(out / "demo-20261026-130000" / "job.json", {"jobId": "demo-20261026-130000", "state": "running", "step": "run"})
    Jobs(out).recover()
    job = read_json(out / "demo-20261026-130000" / "job.json")
    assert job["state"] == "failed" and "다시 시작" in job["message"]
    assert json.loads((out / "demo-20261026-130000" / "job.json").read_text(encoding="utf-8"))["finished_at"]
