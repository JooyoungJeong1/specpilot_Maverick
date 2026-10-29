"""analyze_frontend_js 테스트 (verification2와 같은 키 + 이번에 더한 것)."""
from pathlib import Path

from code_analysis import analyze_frontend_js as af

JS = """
document.addEventListener("DOMContentLoaded", () => {
    const emailInput = document.querySelector("#email");
    const nameInput = document.getElementById("name");
    const button = document.querySelector("#lookup");
    const update = () => {
        button.disabled = !(emailInput.value && nameInput.value);
        fetch(`/api/check?email=${emailInput.value}`);
    };
    [emailInput, nameInput].forEach((el) => el?.addEventListener("input", update));
    document.querySelectorAll(".toggle").forEach((b) => b.addEventListener("click", () => {
        b.classList.toggle("on");
    }));
    if (/^\\S+@\\S+$/.test(emailInput.value)) { window.location.href = "/done"; }
});
"""


def test_parse_js_source():
    r = af.parse_js_source("static/js/a.js", JS)
    assert {"selectors", "event_bindings", "regex_literals", "string_literals", "url_refs"} <= set(r)
    assert {s["var_name"]: s["selector"] for s in r["selectors"]} == {"emailInput": "#email", "nameInput": "#name", "button": "#lookup"}
    b = [x for x in af.user_bindings(r) if x["event_type"] == "input"][0]
    assert b["target"] == "#email, #name" and b["handler"] == "update"
    assert any("button.disabled" in e for e in b["effects"]) and b["effect_targets"] == ["#lookup"]
    t = [x for x in af.user_bindings(r) if x["event_type"] == "click"][0]
    assert t["target"] == ".toggle의 각 요소" and t["handler"] == "<inline function>"
    assert r["regex_literals"]
    assert {(u["method"], u["url"]) for u in r["url_refs"]} == {("GET", "/api/check"), ("GET", "/done")}
    assert all(x["event_type"] != "DOMContentLoaded" for x in af.user_bindings(r))


def test_directory_api_keeps_verification2_shape(tmp_path):
    (tmp_path / "a.js").write_text(JS, encoding="utf-8")
    agg = af.analyze_js_directory(tmp_path)
    assert agg["files"] == ["a.js"] and all(x["file"] == "a.js" for x in agg["selectors"])
