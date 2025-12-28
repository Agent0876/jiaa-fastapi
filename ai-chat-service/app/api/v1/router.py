
from fastapi import APIRouter
from app.api.v1.endpoints import chat, sessions, roadmaps

api_router = APIRouter()

# chat.py has defined routes with absolute paths (e.g. /chat, /ws/chat) to maintain consistency with legacy structure.
api_router.include_router(chat.router, tags=["chat"])

# sessions.py has explicit paths (e.g. /personalities, /sessions)
api_router.include_router(sessions.router, tags=["sessions"])

# roadmaps.py has relative paths corresponding to the /roadmaps resource.
api_router.include_router(roadmaps.router, prefix="/roadmaps", tags=["roadmaps"])
