
from fastapi import APIRouter
from app.api.v1.endpoints import chat, sessions, roadmaps

api_router = APIRouter()

# chat.py routes with /chat prefix
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])

# sessions.py routes
api_router.include_router(sessions.router, tags=["sessions"])

# roadmaps.py routes with /roadmaps prefix
api_router.include_router(roadmaps.router, prefix="/roadmaps", tags=["roadmaps"])
