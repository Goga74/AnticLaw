"""FastAPI HTTP API server for AnticLaw."""

import ipaddress
import logging
from pathlib import Path

from anticlaw import __version__
from anticlaw.core.config import resolve_home
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.search import search_unified

log = logging.getLogger(__name__)


def _is_localhost(client_host: str) -> bool:
    """Check if the request comes from localhost."""
    try:
        addr = ipaddress.ip_address(client_host)
        return addr.is_loopback
    except ValueError:
        return client_host in ("localhost", "127.0.0.1", "::1")


def create_app(
    home: Path | None = None,
    api_key: str | None = None,
    cors_origins: list[str] | None = None,
    enable_ui: bool = False,
):
    """Create and configure the FastAPI application.

    Args:
        home: Override ACL_HOME path.
        api_key: Optional API key for remote access. None = no auth needed.
        cors_origins: List of allowed CORS origins.
        enable_ui: Mount the Web UI at /ui/*.
    """
    try:
        from fastapi import FastAPI, HTTPException, Query, Request
        from fastapi.responses import JSONResponse
    except ImportError as e:
        raise ImportError(
            "FastAPI is required for the HTTP API. "
            "Install with: pip install anticlaw[api]"
        ) from e

    home_path = home or resolve_home()
    db_path = home_path / ".acl" / "meta.db"

    app = FastAPI(
        title="AnticLaw API",
        description="Local-first knowledge base for LLM conversations",
        version=__version__,
    )

    # CORS
    if cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _get_db() -> MetaDB:
        return MetaDB(db_path)

    def _check_auth(request: Request) -> None:
        """Check API key for non-localhost requests."""
        if not api_key:
            return
        client = request.client.host if request.client else "127.0.0.1"
        if _is_localhost(client):
            return
        auth_header = request.headers.get("authorization", "")
        if auth_header == f"Bearer {api_key}":
            return
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/api/health")
    def health(request: Request):
        _check_auth(request)
        return {
            "status": "ok",
            "version": __version__,
            "home": str(home_path),
        }

    @app.get("/api/search")
    def search_endpoint(
        request: Request,
        q: str = Query(..., description="Search query"),
        project: str | None = Query(None, description="Filter by project"),
        result_type: str | None = Query(
            None, alias="type", description="Result type filter",
        ),
        max_results: int = Query(20, ge=1, le=100, description="Max results"),
    ):
        _check_auth(request)
        db = _get_db()
        try:
            result_types = [result_type] if result_type else None
            results = search_unified(
                db, q, project=project, max_results=max_results,
                result_types=result_types,
            )
            return {
                "query": q,
                "count": len(results),
                "results": [
                    {
                        "id": r.chat_id,
                        "title": r.title,
                        "project": r.project_id,
                        "snippet": r.snippet,
                        "score": r.score,
                        "file_path": r.file_path,
                        "type": r.result_type,
                    }
                    for r in results
                ],
            }
        finally:
            db.close()

    @app.post("/api/ask")
    def ask_endpoint(request: Request, body: dict):
        _check_auth(request)
        question = body.get("question", "")
        project = body.get("project")
        if not question:
            raise HTTPException(status_code=400, detail="'question' field required")

        try:
            from anticlaw.llm.qa import ask

            result = ask(question, home_path, project=project)
            return {
                "question": question,
                "answer": result.answer,
                "sources": [
                    {
                        "id": s.chat_id,
                        "title": s.title,
                        "snippet": s.snippet,
                    }
                    for s in (result.sources or [])
                ],
                "error": result.error,
            }
        except ImportError:
            return {
                "question": question,
                "answer": "",
                "sources": [],
                "error": "LLM support not available. Install with: pip install anticlaw[llm]",
            }
        except Exception as e:
            return {
                "question": question,
                "answer": "",
                "sources": [],
                "error": str(e),
            }

    @app.get("/api/projects")
    def projects_endpoint(request: Request):
        _check_auth(request)
        db = _get_db()
        try:
            projects = db.list_projects()
            return {
                "count": len(projects),
                "projects": [
                    {
                        "id": p["id"],
                        "name": p.get("name", ""),
                        "description": p.get("description", ""),
                        "status": p.get("status", ""),
                        "tags": p.get("tags", "[]"),
                    }
                    for p in projects
                ],
            }
        finally:
            db.close()

    @app.get("/api/stats")
    def stats_endpoint(request: Request):
        _check_auth(request)
        db = _get_db()
        try:
            chats = db.list_chats()
            projects = db.list_projects()
            insights_count = db.count_insights()
            source_files_count = db.count_source_files()
            return {
                "chats": len(chats),
                "projects": len(projects),
                "insights": insights_count,
                "source_files": source_files_count,
            }
        finally:
            db.close()

    # Mount Web UI if enabled
    if enable_ui:
        try:
            from anticlaw.ui.app import mount_ui

            mount_ui(app, home_path)
            log.info("Web UI mounted at /ui")
        except ImportError:
            log.warning(
                "Web UI dependencies not installed. "
                "Install with: pip install anticlaw[ui]"
            )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        log.error("Unhandled error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app
