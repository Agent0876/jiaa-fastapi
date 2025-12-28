
from typing import Optional, Dict
from app.db.mongodb import get_collection

async def get_session_config(session_id: str) -> Optional[Dict]:
    """세션 설정 가져오기"""
    try:
        session_configs = await get_collection("session_configs")
        config = await session_configs.find_one({"session_id": session_id})
        return config
    except Exception as e:
        print(f"⚠️ 세션 설정 조회 실패: {e}")
        return None
