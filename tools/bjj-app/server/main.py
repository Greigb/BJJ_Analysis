"""FastAPI entrypoint — creates the app and wires routers + static frontend."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.api import analyse as analyse_api
from server.api import rolls as rolls_api
from server.config import load_settings
from server.db import init_db


def create_app() -> FastAPI:
    settings = load_settings()
    init_db(settings.db_path)

    app = FastAPI(title="BJJ Review App", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(rolls_api.router)
    app.include_router(analyse_api.router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # Serve uploaded videos at /assets/<id>/source.mp4. Created on demand —
    # only mount if the dir exists so dev-fresh installs don't 500 on startup.
    assets_dir = settings.project_root / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/assets",
        StaticFiles(directory=assets_dir, check_dir=False),
        name="assets",
    )

    # Serve the built SvelteKit SPA when the build dir exists (production mode).
    # Must be mounted LAST so /api/* and /assets/* are matched first.
    if settings.frontend_build_dir.exists():
        app.mount(
            "/",
            StaticFiles(directory=settings.frontend_build_dir, html=True),
            name="frontend",
        )

    return app


app = create_app()
