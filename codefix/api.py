"""A small web API for CodeFix Agent, built with FastAPI.

Run it with:   codefix serve
Then open:     http://127.0.0.1:8000/docs   (interactive documentation, generated automatically)

Endpoints:
    GET  /health     is the service running?
    POST /scan       list the functions in a repository
    POST /diagnose   ask the model for a diagnosis and proposed fix (changes nothing)
    POST /fix        run the full repair loop; applies the patch only if "apply": true

Safety:
- Repositories are paths on the server. Only folders inside CODEFIX_REPOS_ROOT
  (default: the folder the server was started in) can be used, so a request cannot
  point the agent at any other folder on the machine.
- /fix is a dry run unless the caller sends "apply": true. In the API, that flag
  is the human approval step from the command line's [y/N] prompt.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from codefix import __version__
from codefix.agent import run_fix, save_run
from codefix.analyzer import scan_repository
from codefix.assistant import diagnose
from codefix.llm import LLM, LLMError

log = logging.getLogger(__name__)

app = FastAPI(
    title="CodeFix Agent",
    version=__version__,
    description="Diagnose and repair bugs in small Python repositories.",
)


# ------------------------------------------------------------------ requests

class ScanRequest(BaseModel):
    repo: str = Field(..., description="Repository path, relative to CODEFIX_REPOS_ROOT", examples=["sample_repo"])


class DiagnoseRequest(ScanRequest):
    issue: str = Field(..., min_length=1, description="The bug report")
    model: str | None = Field(None, description="Model id (default: CODEFIX_MODEL or the built-in default)")
    include_tests: bool = True


class FixRequest(ScanRequest):
    issue: str = Field(..., min_length=1)
    model: str | None = None
    max_attempts: int = Field(3, ge=1, le=5)
    apply: bool = Field(False, description="Apply the winning patch to the repository. False means dry run.")


# -------------------------------------------------------------- dependencies

def repos_root() -> Path:
    return Path(os.getenv("CODEFIX_REPOS_ROOT", ".")).resolve()


def resolve_repo(repo: str) -> Path:
    """Turn a requested repo path into a real folder inside the allowed root, or raise an HTTP error."""
    root = repos_root()
    path = (root / repo).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(status_code=400, detail="Repository must be inside CODEFIX_REPOS_ROOT.")
    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"Repository not found: {repo}")
    return path


def get_llm_factory() -> Callable[[str | None], LLM]:
    """Creates the LLM for a request. Tests replace this with a fake (see tests/test_api.py)."""
    return lambda model=None: LLM(model=model)


def llm_errors() -> tuple[type[Exception], ...]:
    """Errors that mean the model call failed. Anything else is a bug and should not be hidden."""
    errors: list[type[Exception]] = [LLMError]
    try:
        import anthropic

        errors.append(anthropic.APIError)
    except ImportError:
        pass
    return tuple(errors)


# ----------------------------------------------------------------- endpoints

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.post("/scan")
def scan(req: ScanRequest) -> dict:
    result = scan_repository(resolve_repo(req.repo))
    return {
        "files": result.files,
        "functions": [f.to_dict() for f in result.source_functions()],
        "tests": len(result.test_functions()),
        "errors": result.errors,
    }


@app.post("/diagnose")
def diagnose_endpoint(req: DiagnoseRequest, make_llm=Depends(get_llm_factory)) -> dict:
    repo = resolve_repo(req.repo)
    try:
        diag = diagnose(str(repo), req.issue, llm=make_llm(req.model), include_tests=req.include_tests)
    except llm_errors() as exc:
        log.warning("Diagnose failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Model call failed: {exc}") from exc
    return diag.to_dict()


@app.post("/fix")
def fix_endpoint(req: FixRequest, make_llm=Depends(get_llm_factory)) -> dict:
    repo = resolve_repo(req.repo)
    try:
        result = run_fix(
            repo,
            req.issue,
            llm=make_llm(req.model),
            max_attempts=req.max_attempts,
            approve=lambda patch, attempt: req.apply,
        )
    except llm_errors() as exc:
        log.warning("Fix failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Model call failed: {exc}") from exc

    log_path = save_run(result)
    winner = result.winning_attempt
    return {
        "status": result.status,
        "applied": result.applied,
        "attempts": len(result.attempts),
        "patch": winner.patch.diff() if winner else None,
        "fixed_tests": winner.fixed if winner else [],
        "totals": result.totals(),
        "duration_s": result.duration_s,
        "run_log": str(log_path),
    }
