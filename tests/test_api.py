"""Tests for the web API. TestClient sends requests to the app without starting a server.

The real LLM is swapped for a fake with FastAPI's dependency_overrides, so no API calls are made.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codefix.api import app, get_llm_factory
from codefix.llm import LLMError, Usage

SAMPLE_REPO = Path(__file__).resolve().parent.parent / "sample_repo"

FIX = {
    "summary": "s", "file": "cart.py", "function": "apply_discount", "root_cause": "r", "confidence": "high",
    "fixed_code": (
        "def apply_discount(total, percent):\n"
        '    """Return the total after a percentage discount. percent must be between 0 and 100."""\n'
        "    if percent < 0 or percent > 100:\n"
        '        raise ValueError("percent must be between 0 and 100")\n'
        "    return round(total * (100 - percent) / 100, 2)"
    ),
}


class FakeLLM:
    def call_tool(self, system, user, tool):
        return FIX, Usage(model="fake", input_tokens=100, output_tokens=50, latency_s=0.0)


class FailingLLM:
    def call_tool(self, system, user, tool):
        raise LLMError("model did not call the tool")


@pytest.fixture
def client(tmp_path, monkeypatch):
    shutil.copytree(SAMPLE_REPO, tmp_path / "sample_repo")
    monkeypatch.setenv("CODEFIX_REPOS_ROOT", str(tmp_path))
    monkeypatch.chdir(tmp_path)  # run logs are written to ./runs
    app.dependency_overrides[get_llm_factory] = lambda: (lambda model=None: FakeLLM())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_scan(client):
    response = client.post("/scan", json={"repo": "sample_repo"})
    assert response.status_code == 200
    names = [f["qualified_name"] for f in response.json()["functions"]]
    assert "apply_discount" in names and "Cart.add" in names


def test_repo_outside_root_is_refused(client):
    response = client.post("/scan", json={"repo": "../.."})
    assert response.status_code == 400


def test_missing_repo_is_404(client):
    assert client.post("/scan", json={"repo": "nope"}).status_code == 404


def test_diagnose(client):
    response = client.post("/diagnose", json={"repo": "sample_repo", "issue": "Discount makes the price tiny"})
    assert response.status_code == 200
    body = response.json()
    assert body["function"] == "apply_discount"
    assert body["warnings"] == []


def test_fix_is_a_dry_run_by_default(client, tmp_path):
    before = (tmp_path / "sample_repo" / "cart.py").read_text()
    response = client.post("/fix", json={"repo": "sample_repo", "issue": "Discount makes the price tiny"})
    body = response.json()
    assert body["status"] == "fixed_not_applied"
    assert body["applied"] is False
    assert "+    return round(total * (100 - percent) / 100, 2)" in body["patch"]
    assert (tmp_path / "sample_repo" / "cart.py").read_text() == before


def test_fix_applies_when_asked(client, tmp_path):
    response = client.post("/fix", json={"repo": "sample_repo", "issue": "Discount bug", "apply": True})
    assert response.json()["status"] == "fixed"
    assert "(100 - percent)" in (tmp_path / "sample_repo" / "cart.py").read_text()


@pytest.mark.parametrize("body", [
    {"repo": "sample_repo", "issue": ""},                       # empty issue
    {"repo": "sample_repo", "issue": "x", "max_attempts": 10},  # too many attempts
    {"issue": "x"},                                              # repo missing
])
def test_invalid_requests_are_rejected(client, body):
    assert client.post("/fix", json=body).status_code == 422


def test_model_failure_is_502(client):
    app.dependency_overrides[get_llm_factory] = lambda: (lambda model=None: FailingLLM())
    response = client.post("/diagnose", json={"repo": "sample_repo", "issue": "Discount bug"})
    assert response.status_code == 502
    assert "did not call the tool" in response.json()["detail"]
