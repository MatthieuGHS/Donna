"""FastAPI application — tools layer for Donna."""

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.logging_config import setup_logging
from api.rate_limit import limiter
from api.routes import calendar, pending, rules, todos
from config import settings

setup_logging(settings.environment)
logger = structlog.get_logger(__name__)

app = FastAPI(
    title="Donna API",
    docs_url="/docs" if not settings.is_prod else None,  # Disable docs in prod
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.is_prod else None,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Routes
app.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
app.include_router(todos.router, prefix="/todos", tags=["todos"])
app.include_router(rules.router, prefix="/rules", tags=["rules"])
app.include_router(pending.router, prefix="/pending", tags=["pending"])


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all unhandled exceptions. Never expose stack traces to client."""
    logger.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "environment": settings.environment}


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=not settings.is_prod,
    )
