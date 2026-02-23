"""Web UI routes for AnticLaw — Jinja2 + HTMX + Tailwind CSS."""

import json
import logging
from pathlib import Path

from anticlaw import __version__
from anticlaw.core.meta_db import MetaDB
from anticlaw.core.search import search_unified

log = logging.getLogger(__name__)

# Dependency guard
try:
    from jinja2 import Environment, FileSystemLoader

    HAS_UI = True
except ImportError:
    HAS_UI = False

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _parse_chats(rows: list[dict]) -> list[dict]:
    """Parse JSON tags strings into lists for template rendering."""
    result = []
    for row in rows:
        chat = dict(row)
        tags = chat.get("tags", "[]")
        if isinstance(tags, str):
            try:
                chat["tags"] = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                chat["tags"] = []
        result.append(chat)
    return result


def mount_ui(app, home_path: Path) -> None:
    """Register all /ui/* routes on the FastAPI app.

    Args:
        app: FastAPI application instance.
        home_path: ACL_HOME path for data access.
    """
    if not HAS_UI:
        log.warning("Jinja2 not installed — UI routes disabled")
        return

    from fastapi import Query
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=True,
    )

    # Ensure static dir exists and mount it
    static_dir = Path(__file__).parent / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/ui/static", StaticFiles(directory=str(static_dir)), name="ui-static")

    db_path = home_path / ".acl" / "meta.db"

    def _get_db() -> MetaDB:
        return MetaDB(db_path)

    def _render(template: str, **ctx) -> HTMLResponse:
        ctx.setdefault("version", __version__)
        tmpl = env.get_template(template)
        html = tmpl.render(**ctx)
        return HTMLResponse(html)

    # --- Full-page routes ---

    @app.get("/ui", response_class=HTMLResponse)
    @app.get("/ui/", response_class=HTMLResponse)
    def ui_dashboard():
        db = _get_db()
        try:
            stats = {
                "chats": len(db.list_chats()),
                "projects": len(db.list_projects()),
                "insights": db.count_insights(),
                "source_files": db.count_source_files(),
            }
            return _render("dashboard.html", active="dashboard", stats=stats)
        finally:
            db.close()

    @app.get("/ui/search", response_class=HTMLResponse)
    def ui_search(
        q: str = Query("", alias="q"),
        project: str = Query("", alias="project"),
        result_type: str = Query("", alias="type"),
    ):
        db = _get_db()
        try:
            projects = db.list_projects()
            results = []
            if q:
                result_types = [result_type] if result_type else None
                raw = search_unified(
                    db, q,
                    project=project or None,
                    max_results=20,
                    result_types=result_types,
                )
                results = [
                    {
                        "id": r.chat_id,
                        "title": r.title,
                        "project": r.project_id,
                        "snippet": r.snippet,
                        "score": r.score,
                        "type": r.result_type,
                    }
                    for r in raw
                ]
            return _render(
                "search.html",
                active="search",
                query=q,
                projects=projects,
                results=results,
                selected_project=project,
                selected_type=result_type,
            )
        finally:
            db.close()

    @app.get("/ui/projects", response_class=HTMLResponse)
    def ui_projects(
        project: str = Query("", alias="project"),
    ):
        db = _get_db()
        try:
            projects = db.list_projects()
            chats = []
            if project:
                chats = _parse_chats(db.list_chats(project_id=project))
            return _render(
                "projects.html",
                active="projects",
                projects=projects,
                chats=chats,
                selected_project=project,
            )
        finally:
            db.close()

    @app.get("/ui/inbox", response_class=HTMLResponse)
    def ui_inbox():
        db = _get_db()
        try:
            chats = _parse_chats(db.list_chats(project_id="_inbox"))
            return _render("inbox.html", active="inbox", chats=chats)
        finally:
            db.close()

    # --- HTMX partial routes ---

    @app.get("/ui/search/results", response_class=HTMLResponse)
    def ui_search_results(
        q: str = Query("", alias="q"),
        project: str = Query("", alias="project"),
        result_type: str = Query("", alias="type"),
    ):
        db = _get_db()
        try:
            results = []
            if q:
                result_types = [result_type] if result_type else None
                raw = search_unified(
                    db, q,
                    project=project or None,
                    max_results=20,
                    result_types=result_types,
                )
                results = [
                    {
                        "id": r.chat_id,
                        "title": r.title,
                        "project": r.project_id,
                        "snippet": r.snippet,
                        "score": r.score,
                        "type": r.result_type,
                    }
                    for r in raw
                ]
            return _render("_search_results.html", results=results)
        finally:
            db.close()

    @app.get("/ui/projects/chats", response_class=HTMLResponse)
    def ui_project_chats(
        project: str = Query("", alias="project"),
    ):
        db = _get_db()
        try:
            chats = []
            if project:
                chats = _parse_chats(db.list_chats(project_id=project))
            return _render(
                "_chat_list.html",
                chats=chats,
                selected_project=project,
            )
        finally:
            db.close()
