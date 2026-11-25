from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sakshya import __version__
from sakshya.api.workspace import Workspace, WorkspaceError
from sakshya.custody.intake import ManifestError
from sakshya.pipeline import bundle
from sakshya.report.render import render_report
from sakshya.views import link_detail, observation_detail

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
logger = logging.getLogger("sakshya")


class ActionRequest(BaseModel):
    type: str = Field(pattern=r"^(confirm_link|reject_link|forbid_merge|revoke)$")
    target: str | list[str]
    reason: str = Field(min_length=3, max_length=500)
    actor: str = Field(default="investigator", max_length=80)


def _warm(workspace: Workspace) -> None:
    for case_id in workspace.case_ids():
        try:
            workspace.analysis(case_id)
        except Exception:
            logger.exception("Could not analyse case %s at start-up", case_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    workspace: Workspace = app.state.workspace
    workspace.seed_demo_cases()
    threading.Thread(target=_warm, args=(workspace,), name="sakshya-warm", daemon=True).start()
    yield


def create_app(workspace: Workspace | None = None) -> FastAPI:
    app = FastAPI(
        title="Sakshya",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.workspace = workspace or Workspace()

    @app.exception_handler(WorkspaceError)
    async def workspace_error(_: Request, exc: WorkspaceError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ManifestError)
    async def manifest_error(_: Request, exc: ManifestError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    def ws() -> Workspace:
        return app.state.workspace

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "cases": len(ws().case_ids())}

    @app.get("/api/cases")
    def cases() -> list[dict[str, Any]]:
        return ws().summaries()

    @app.get("/api/cases/{case_id}")
    def case(case_id: str) -> dict[str, Any]:
        return ws().bundle(case_id)

    @app.get("/api/cases/{case_id}/reach")
    def reach(
        case_id: str,
        as_of: float | None = Query(default=None),
        policy: str = Query(default="pro_rata", pattern=r"^(pro_rata|fifo)$"),
    ) -> dict[str, Any]:
        return ws().analysis(case_id).reach(as_of, policy)

    @app.get("/api/cases/{case_id}/links/{link_id}")
    def link(case_id: str, link_id: str) -> dict[str, Any]:
        detail = link_detail(ws().analysis(case_id), link_id)
        if detail is None:
            raise HTTPException(404, "Link not found")
        return detail

    @app.get("/api/cases/{case_id}/observations/{obs_id}")
    def observation(case_id: str, obs_id: str) -> dict[str, Any]:
        detail = observation_detail(ws().analysis(case_id), obs_id)
        if detail is None:
            raise HTTPException(404, "Observation not found")
        return detail

    @app.post("/api/cases/{case_id}/actions")
    def act(case_id: str, request: ActionRequest) -> dict[str, Any]:
        return ws().act(case_id, request.type, request.target, request.reason, request.actor)

    @app.get("/api/cases/{case_id}/report", response_class=HTMLResponse)
    def report(case_id: str) -> HTMLResponse:
        analysis = ws().analysis(case_id)
        html = render_report(analysis, ws().bundle(case_id))
        digest = ws().record_report(case_id, html)
        return HTMLResponse(html, headers={"X-Report-SHA256": digest})

    @app.get("/api/cases/{case_id}/export.json")
    def export(case_id: str) -> JSONResponse:
        data = bundle(ws().analysis(case_id))
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{case_id}_analysis.json"'})

    @app.post("/api/cases")
    async def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        payload = await file.read()
        case_id = ws().upload(payload)
        return {"id": case_id, "summary": ws().bundle(case_id)["decision"]}

    @app.get("/api/evaluation")
    def evaluation() -> dict[str, Any]:
        data = ws().evaluation()
        if data is None:
            raise HTTPException(404, "Evaluation results have not been generated")
        return data

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
