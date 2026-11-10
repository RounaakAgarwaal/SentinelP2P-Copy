from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes import router as api_router
from app.core.config import PROJECT_ROOT, settings

app = FastAPI(title=settings.title)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
FRONTEND_BUILD_COMMAND = "npm ci --prefix frontend && npm run build --prefix frontend"


def _frontend_response(path: str = "") -> FileResponse:
    """Serve built assets or the SPA entry point after the API router."""
    # API misses must remain API 404s even when the frontend has not been built.
    if path == "api" or path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    if not FRONTEND_DIST.is_dir() or not FRONTEND_INDEX.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "The React frontend build is missing. From the repository root, "
                f"run: {FRONTEND_BUILD_COMMAND}"
            ),
        )

    if path:
        root = FRONTEND_DIST.resolve()
        candidate = (FRONTEND_DIST / path).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)
    return FileResponse(FRONTEND_INDEX)


@app.get("/", include_in_schema=False)
def frontend_root() -> FileResponse:
    return _frontend_response()


@app.get("/{path:path}", include_in_schema=False)
def frontend_fallback(path: str) -> FileResponse:
    return _frontend_response(path)
