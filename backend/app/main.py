"""FastAPI application entry point."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.settings import settings
from app.api.v1 import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="文档深度研究服务",
    description="Document Deep Research Service API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Return 500 with error detail for debugging (path helps correlate with browser Network tab)."""
    path = getattr(request.url, "path", "") if request is not None else ""
    logger.exception("Unhandled exception on %s: %s", path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "path": path},
    )


@app.get("/health")
def health_check():
    return {"status": "ok"}
