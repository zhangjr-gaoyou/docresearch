"""API v1 router."""
from fastapi import APIRouter

from app.api.v1 import collections, search, research, tools, prompts

api_router = APIRouter()

api_router.include_router(collections.router, prefix="/collections", tags=["collections"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(prompts.router, prefix="/prompts", tags=["prompts"])
