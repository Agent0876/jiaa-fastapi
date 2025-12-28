
from typing import Optional
from pydantic import BaseModel

class PersonalityResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class SelectPersonalityRequest(BaseModel):
    session_id: str
    personality_id: int
    user_id: Optional[str] = None  # UUID 문자열


class UpdateSessionModeRequest(BaseModel):
    mode: str  # 'chat' or 'roadmap'
