
from typing import Optional, List, Dict
from pydantic import BaseModel

class StartRoadmapRequest(BaseModel):
    session_id: str
    user_id: Optional[str] = None  # UUID 문자열


class RoadmapResponse(BaseModel):
    id: str  # MongoDB ObjectId는 문자열
    name: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    created_at: str
    updated_at: str
    items: List[Dict]


class UpdateRoadmapItemRequest(BaseModel):
    is_completed: bool
