
from typing import Optional, List, Dict
from pydantic import BaseModel
from app.core.config import settings

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None  # UUID 문자열
    model_id: Optional[str] = settings.DEFAULT_MODEL_ID
    max_tokens: Optional[int] = 100000
    temperature: Optional[float] = 0.7
    conversation_history: Optional[List[Dict]] = None


class ChatResponse(BaseModel):
    response: str
    model_id: str
    session_id: str


class SearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None  # UUID 문자열
    limit: Optional[int] = 5


class SaveMessageRequest(BaseModel):
    role: str
    content: str
