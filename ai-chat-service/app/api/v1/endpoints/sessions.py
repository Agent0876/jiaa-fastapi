
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from app.db.mongodb import get_collection
from app.models.session import (
    PersonalityResponse,
    SelectPersonalityRequest,
    UpdateSessionModeRequest
)

router = APIRouter()

@router.get("/personalities", response_model=List[PersonalityResponse])
async def get_personalities():
    """사용 가능한 성격 캐릭터 목록 조회"""
    try:
        personalities_collection = await get_collection("personalities")
        cursor = personalities_collection.find({})
        personalities = await cursor.to_list(length=None)
        
        # MongoDB의 _id를 정수형 ID로 매핑 (기존 API 호환성 유지)
        result = []
        for idx, p in enumerate(personalities):
            result.append(PersonalityResponse(
                id=idx + 1,  # 1부터 시작하는 ID
                name=p.get("name", ""),
                description=p.get("description")
            ))
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"성격 목록 조회 중 오류 발생: {str(e)}")


@router.post("/personalities/select")
async def select_personality(request: SelectPersonalityRequest):
    """세션에 성격 캐릭터 선택"""
    try:
        # 성격 존재 확인 (personality_id는 1부터 시작하는 인덱스로 가정)
        personalities_collection = await get_collection("personalities")
        cursor = personalities_collection.find({})
        all_personalities = await cursor.to_list(length=None)
        
        if request.personality_id < 1 or request.personality_id > len(all_personalities):
            raise HTTPException(status_code=404, detail="성격을 찾을 수 없습니다.")
        
        personality = all_personalities[request.personality_id - 1]
        
        # 세션 설정 가져오기 또는 생성
        session_configs = await get_collection("session_configs")
        config = await session_configs.find_one({"session_id": request.session_id})
        
        update_data = {
            "personality_id": request.personality_id,
            "mode": "chat",
            "updated_at": datetime.utcnow()
        }
        
        if request.user_id:
            update_data["user_id"] = request.user_id
        
        if not config:
            # 새 세션 설정 생성
            config_doc = {
                "session_id": request.session_id,
                "user_id": request.user_id,
                "personality_id": request.personality_id,
                "mode": "chat",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await session_configs.insert_one(config_doc)
        else:
            # 기존 세션 설정 업데이트
            await session_configs.update_one(
                {"session_id": request.session_id},
                {"$set": update_data}
            )
        
        return {
            "message": f"{personality.get('name')} 성격이 선택되었습니다.",
            "session_id": request.session_id,
            "personality": {
                "id": request.personality_id,
                "name": personality.get("name")
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"성격 선택 중 오류 발생: {str(e)}")


@router.put("/sessions/{session_id}/mode")
async def update_session_mode(session_id: str, request: UpdateSessionModeRequest):
    """세션 모드 업데이트 (chat <-> roadmap)"""
    try:
        session_configs = await get_collection("session_configs")
        
        # 세션 존재 확인
        config = await session_configs.find_one({"session_id": session_id})
        if not config:
            # 세션이 없으면 에러 (WebSocket 접속 시 생성됨)
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        
        # 모드 업데이트
        await session_configs.update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "mode": request.mode,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        return {"status": "success", "session_id": session_id, "mode": request.mode}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"세션 모드 업데이트 중 오류: {str(e)}")


@router.get("/sessions/user/{user_id}")
async def get_user_sessions(user_id: str):
    """사용자별 세션 목록 조회"""
    try:
        session_configs = await get_collection("session_configs")
        cursor = session_configs.find({"user_id": user_id})
        sessions = await cursor.to_list(length=None)
        
        return {
            "user_id": user_id,
            "sessions": [
                {
                    "session_id": s.get("session_id"),
                    "personality_id": s.get("personality_id"),
                    "mode": s.get("mode"),
                    "created_at": s.get("created_at").isoformat() if s.get("created_at") else None,
                    "updated_at": s.get("updated_at").isoformat() if s.get("updated_at") else None
                }
                for s in sessions
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"세션 목록 조회 중 오류 발생: {str(e)}")


@router.get("/debug/personalities")
async def debug_personalities():
    """디버깅용: 성격 목록 직접 조회"""
    try:
        personalities_collection = await get_collection("personalities")
        cursor = personalities_collection.find({})
        personalities = await cursor.to_list(length=None)
        
        return {
            "count": len(personalities),
            "personalities": [
                {
                    "id": str(p.get("_id")),
                    "name": p.get("name"),
                    "description": p.get("description")
                }
                for p in personalities
            ]
        }
    except Exception as e:
        import traceback
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
