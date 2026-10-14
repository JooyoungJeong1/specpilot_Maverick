"""입력 점검(preflight)과 게이트 판정 테스트. 좌표를 지정해 만든 작은 PDF를 쓴다 (API 키 필요 없음).

pdftotext(poppler)가 없는 PC에서는 좌표가 필요한 테스트를 건너뛰고, 없을 때의 동작(경고만 남김)을 따로 본다.
"""
import shutil

import pytest
from pypdf import PdfReader, PdfWriter

from specpilot import pdf_utils, preflight
from specpilot.cli import main
from tests.helpers import make_pdf, screen_page

needs_pdftotext = pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext(poppler)가 없음")
DESC = [0, 1, 2, 3, 4, 5]


@pytest.fixture
def no_pdftotext(monkeypatch):
    real = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None if name == "pdftotext" else real(name, *a, **k))


def profile(*screens, flows=()):
    return {"screens": [{"screen_id": sid, "name": sid, "pages": pages, "state_pages": [], "repeats_from": rf}
                        for sid, pages, rf in screens],
            "flows": list(flows)}


# ---------- 입력 점검 ----------

@needs_pdftotext
def test_good_pdf_passes_with_full_checklist(tmp_path):
    pdf = make_pdf(tmp_path / "ok.pdf", [screen_page(DESC), screen_page([0, 1, 2], actions="ABC")])
    r = preflight.run_preflight(pdf)
    assert r["verdict"] == "통과" and r["extractor"] == "pdftotext"
    assert r["pages"]["1"]["items"] == [f"Description {i}" for i in DESC] + ["Action A", "Action B"]
    assert preflight.checklist(r, [1, 2]) == {f"Description {i}" for i in DESC} | {"Action A", "Action B", "Action C"}
    assert r["pages"]["1"]["status"] == "통과" and r["pages"]["1"]["marker_match"] == 1.0


@needs_pdftotext
def test_cropped_picture_is_a_warning_not_a_rejection(tmp_path):
    # 그림에 마커 1~3만 있음 (4, 5와 Action B가 잘림) → 60% 일치, 경고만
    pdf = make_pdf(tmp_path / "crop.pdf", [screen_page(DESC, markers=[1, 2, 3], letters="A")])
    r = preflight.run_preflight(pdf)
    page = r["pages"]["1"]
    assert r["verdict"] == "통과" and page["status"] == "경고"
    assert page["missing_in_picture"] == ["Description 4", "Description 5"]
    assert page["letters_missing_in_picture"] == ["Action B"]
    assert "그림에 없는 설명 번호" in preflight.format_preflight(r)


@needs_pdftotext
def test_markers_not_matching_on_most_pages_rejects_document(tmp_path):
    bad = screen_page(DESC, markers=[1])                 # 5개 중 1개만 맞음 (20%)
    pdf = make_pdf(tmp_path / "bad.pdf", [bad, bad, screen_page(DESC)])
    r = preflight.run_preflight(pdf)
    assert r["verdict"] == "반려" and "맞지 않는 쪽이 2/3쪽" in r["reasons"][0]


@needs_pdftotext
def test_numbering_gap_is_reported(tmp_path):
    pdf = make_pdf(tmp_path / "gap.pdf", [screen_page([0, 1, 2, 4, 5])])
    r = preflight.run_preflight(pdf)
    assert r["verdict"] == "통과" and r["pages"]["1"]["numbering_gaps"] == ["Description 3"]


@needs_pdftotext
def test_no_description_table_is_unsupported_format(tmp_path):
    pdf = make_pdf(tmp_path / "other.pdf", [[(80, 60, "Some storyboard text"), (300, 300, "Next scene")]])
    r = preflight.run_preflight(pdf)
    assert r["verdict"] == "반려" and "지원하지 않는 기획서 양식" in r["reasons"][0]


def test_scanned_pdf_without_text_is_rejected(tmp_path):
    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(width=842, height=595)
    with open(tmp_path / "scan.pdf", "wb") as f:
        w.write(f)
    r = preflight.run_preflight(tmp_path / "scan.pdf")
    assert r["verdict"] == "반려" and "글자층이 없는 쪽이 3/3쪽" in r["reasons"][0]


def test_broken_and_encrypted_pdf_are_rejected(tmp_path):
    (tmp_path / "broken.pdf").write_bytes(b"not a pdf at all")
    assert "PDF를 열 수 없습니다" in preflight.run_preflight(tmp_path / "broken.pdf")["reasons"][0]
    src = make_pdf(tmp_path / "plain.pdf", [screen_page(DESC)])
    w = PdfWriter()
    w.append(PdfReader(str(src)))
    w.encrypt("secret")
    with open(tmp_path / "locked.pdf", "wb") as f:
        w.write(f)
    assert "암호" in preflight.run_preflight(tmp_path / "locked.pdf")["reasons"][0]


def test_without_pdftotext_only_warns(tmp_path, no_pdftotext):
    pdf = make_pdf(tmp_path / "ok.pdf", [screen_page(DESC, markers=[1])])   # 마커가 거의 없어도
    r = preflight.run_preflight(pdf)
    assert r["verdict"] == "통과" and r["extractor"] == "pypdf"             # 좌표가 없으면 마커 검사는 건너뛴다
    assert any("poppler" in w for w in r["warnings"])
    assert r["pages"]["1"]["marker_match"] is None


# ---------- 게이트 (① 이후, 화면 단위) ----------

@needs_pdftotext
def test_gate_rejects_screen_and_ignores_repeated_items(tmp_path):
    pages = [screen_page(DESC),                                   # p1 A화면: 정상
             screen_page(DESC, markers=[1]),                      # p2 B화면: 그림과 번호가 거의 안 맞음 → 반려
             screen_page([0], actions="ABC", markers=[], letters="C"),   # p3 C팝업: A, B는 부모(A화면)와 같은 항목
             screen_page(DESC)]                                   # p4 D화면
    pdf = make_pdf(tmp_path / "doc.pdf", pages)
    r = preflight.run_preflight(pdf)
    prof = profile(("SCR-001", [1], None), ("SCR-002", [2], None),
                   ("SCR-003", [3], {"screen_id": "SCR-001", "items": ["Description 0", "Action A", "Action B"]}),
                   ("SCR-004", [4], None),
                   flows=[{"from": "SCR-001", "trigger": "next", "to": "SCR-099", "source": "Action A"},
                          {"from": "SCR-001", "trigger": "help", "to": "outside help site", "source": "Action B"}])
    gate = preflight.gate_screens(r, prof)
    assert gate["verdict"] == "통과"                                  # 4개 중 1개만 반려
    assert gate["screens"]["SCR-002"]["verdict"] == "반려" and "1/5 일치" in gate["screens"]["SCR-002"]["reasons"][0]
    assert gate["screens"]["SCR-003"]["verdict"] == "통과"                # 부모에서 되풀이한 A, B는 그림에 없어도 정상
    assert gate["screens"]["SCR-001"]["verdict"] == "통과"
    assert any("설계서에 없는 화면 ID" in w for w in gate["warnings"])
    assert any("화면 ID가 없음" in w for w in gate["warnings"])

    prof2 = profile(("SCR-001", [1], None), ("SCR-002", [2], None))         # 2개 중 1개 반려 → 절반 → 전체 반려
    assert preflight.gate_screens(r, prof2)["verdict"] == "반려"
    prof3 = profile(("SCR-001", [1], None), ("SCR-004", [4], None))
    assert any("어느 화면에도 속하지 않은 쪽" in w for w in preflight.gate_screens(r, prof3)["warnings"])


# ---------- 원문 대조, 항목 원문 ----------

@needs_pdftotext
def test_text_index_and_item_text(tmp_path):
    pdf = make_pdf(tmp_path / "t.pdf", [screen_page(DESC)])
    idx = pdf_utils.TextIndex(pdf)
    assert idx.find("charlie rule applies here") == "exact"
    assert idx.find("charlie rule aplies here") == "approx"
    assert idx.find("zulu rule applies elsewhere") is None
    assert pdf_utils.item_text(pdf, 1, "Description 2") == "2 charlie rule applies here"


def test_text_index_without_pdftotext_is_weak(tmp_path, no_pdftotext):
    pdf = make_pdf(tmp_path / "t.pdf", [screen_page(DESC)])
    idx = pdf_utils.TextIndex(pdf)
    assert idx.strong is False and idx.find("charlie rule applies here") == "exact"


# ---------- 명령 ----------

def test_check_and_run_stop_on_rejected_pdf(tmp_path, monkeypatch, capsys):
    w = PdfWriter()
    w.add_blank_page(width=842, height=595)
    with open(tmp_path / "scan.pdf", "wb") as f:
        w.write(f)
    assert main(["check", "--pdf", str(tmp_path / "scan.pdf")]) == 3
    monkeypatch.setenv("SPECPILOT_OUTPUT_DIR", str(tmp_path / "out"))
    assert main(["run", "--pdf", str(tmp_path / "scan.pdf"), "--name", "r1", "--dry-run"]) == 3
    assert (tmp_path / "out" / "r1" / "preflight.json").exists()
    assert not (tmp_path / "out" / "r1" / "prompts_preview").exists()    # ①까지 가지 않음
    assert "반려" in capsys.readouterr().out


def test_korean_path_retries_with_ascii_copy(tmp_path, monkeypatch):
    # 일부 Windows용 pdftotext는 한글 경로를 못 연다 → 영문 이름의 임시 사본으로 다시 시도
    pdf = make_pdf(tmp_path / "기획서.pdf", [screen_page(DESC)])
    real = pdf_utils._run_pdftotext
    seen = []

    def fussy(args):
        seen.append(args[-2] if args[-1] == "-" else args[-1])
        return None if any(not a.isascii() for a in args) else real(args)

    monkeypatch.setattr(pdf_utils, "_run_pdftotext", fussy)
    monkeypatch.setattr(pdf_utils, "has_pdftotext", lambda: True)
    if shutil.which("pdftotext") is None:
        pytest.skip("pdftotext(poppler)가 없음")
    out = pdf_utils._pdftotext([str(pdf), "-"])
    assert out is not None and "charlie" in out and len(seen) == 2 and seen[1].endswith("input.pdf")
