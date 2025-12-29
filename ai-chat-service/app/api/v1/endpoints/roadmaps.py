
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
from bson.errors import InvalidId

from app.db.mongodb import get_collection
from app.models.roadmap import (
    RoadmapResponse,
    UpdateRoadmapItemRequest
)
from app.services.roadmap import generate_day_details, extract_and_save_keywords

router = APIRouter()

@router.get("", response_model=List[RoadmapResponse])
async def get_roadmaps(user_id: Optional[str] = None):
    """사용자별 로드맵 목록 조회"""
    try:
        roadmaps_collection = await get_collection("roadmaps")
        
        query_filter = {}
        if user_id:
            query_filter["user_id"] = user_id
        
        cursor = roadmaps_collection.find(query_filter).sort("created_at", -1)
        roadmaps = await cursor.to_list(length=None)
        
        result = []
        for roadmap in roadmaps:
            items = roadmap.get("items", [])
            formatted_items = []
            for idx, item in enumerate(items):
                # 새 구조: tasks 배열이 있는 경우
                tasks = item.get("tasks", [])
                if tasks:
                    formatted_items.append({
                        "id": idx,
                        "day": item.get("day"),
                        "tasks": [
                            {
                                "rank": task.get("rank", 0),
                                "content": task.get("content", ""),
                                "time": task.get("time", ""),
                                "is_completed": task.get("is_completed", 0),
                                "completed_at": task.get("completed_at").isoformat() if task.get("completed_at") else None,
                                "details": task.get("details")
                            }
                            for task in tasks
                        ],
                        "created_at": item.get("created_at").isoformat() if item.get("created_at") else None
                    })
                else:
                    # 레거시 구조
                    formatted_items.append({
                        "id": idx,
                        "day": item.get("day"),
                        "content": item.get("content", ""),
                        "time": item.get("time", ""),
                        "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                        "is_completed": bool(item.get("is_completed", 0)),
                        "completed_at": item.get("completed_at").isoformat() if item.get("completed_at") else None
                    })
            
            result.append({
                "id": str(roadmap.get("_id")),
                "name": roadmap.get("name", "로드맵"),
                "user_id": roadmap.get("user_id"),
                "session_id": roadmap.get("session_id"),
                "created_at": roadmap.get("created_at").isoformat() if roadmap.get("created_at") else None,
                "updated_at": roadmap.get("updated_at").isoformat() if roadmap.get("updated_at") else None,
                "items": formatted_items
            })
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로드맵 목록 조회 중 오류 발생: {str(e)}")


@router.get("/{roadmap_id}", response_model=RoadmapResponse)
async def get_roadmap(roadmap_id: str):
    """특정 로드맵 상세 조회"""
    try:
        roadmaps_collection = await get_collection("roadmaps")
        
        try:
            object_id = ObjectId(roadmap_id)
            roadmap = await roadmaps_collection.find_one({"_id": object_id})
        except (InvalidId, ValueError, TypeError):
            print(f"⚠️ ObjectId 변환 실패, 문자열로 검색 시도: {roadmap_id}")
            roadmap = await roadmaps_collection.find_one({"_id": roadmap_id})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail=f"로드맵을 찾을 수 없습니다. (ID: {roadmap_id})")
        
        items = roadmap.get("items", [])
        formatted_items = []
        for idx, item in enumerate(items):
            tasks = item.get("tasks", [])
            if tasks:
                formatted_items.append({
                    "id": idx,
                    "day": item.get("day"),
                    "tasks": [
                        {
                            "rank": task.get("rank", 0),
                            "content": task.get("content", ""),
                            "time": task.get("time", ""),
                            "is_completed": task.get("is_completed", 0),
                            "completed_at": task.get("completed_at").isoformat() if task.get("completed_at") else None,
                            "details": task.get("details")
                        }
                        for task in tasks
                    ],
                    "created_at": item.get("created_at").isoformat() if item.get("created_at") else None
                })
            else:
                formatted_items.append({
                    "id": idx,
                    "day": item.get("day"),
                    "content": item.get("content", ""),
                    "time": item.get("time", ""),
                    "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                    "is_completed": bool(item.get("is_completed", 0)),
                    "completed_at": item.get("completed_at").isoformat() if item.get("completed_at") else None
                })
        
        return {
            "id": str(roadmap.get("_id")),
            "name": roadmap.get("name", "로드맵"),
            "user_id": roadmap.get("user_id"),
            "session_id": roadmap.get("session_id"),
            "created_at": roadmap.get("created_at").isoformat() if roadmap.get("created_at") else None,
            "updated_at": roadmap.get("updated_at").isoformat() if roadmap.get("updated_at") else None,
            "items": formatted_items
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로드맵 조회 중 오류 발생: {str(e)}")


@router.post("/{roadmap_id}/generate-details/{day}")
async def generate_roadmap_day_details(roadmap_id: str, day: int):
    """특정 일차의 과업 상세 내용 생성"""
    try:
        roadmaps = await get_collection("roadmaps")
        roadmap = await roadmaps.find_one({"_id": ObjectId(roadmap_id)})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
        
        goal = roadmap.get("name", "학습")
        success = await generate_day_details(roadmap_id, day, goal)
        
        if success:
            return {"status": "success", "message": f"Day {day} 상세 생성 완료"}
        else:
            raise HTTPException(status_code=500, detail="상세 생성 실패")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{roadmap_id}/generate-today-details")
async def generate_today_details(roadmap_id: str):
    """오늘 날짜에 해당하는 과업 상세 내용 생성"""
    try:
        roadmaps = await get_collection("roadmaps")
        roadmap = await roadmaps.find_one({"_id": ObjectId(roadmap_id)})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
        
        items = roadmap.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="로드맵에 항목이 없습니다")
        
        first_item = items[0]
        start_date = first_item.get("created_at")
        if not start_date:
            raise HTTPException(status_code=400, detail="시작일을 찾을 수 없습니다")
        
        today = datetime.utcnow()
        days_diff = (today - start_date).days + 1
        
        if days_diff < 1 or days_diff > len(items):
            raise HTTPException(status_code=400, detail=f"오늘({days_diff}일차)은 로드맵 범위를 벗어났습니다")
        
        goal = roadmap.get("name", "학습")
        success = await generate_day_details(roadmap_id, days_diff, goal)
        
        if success:
            return {"status": "success", "message": f"오늘(Day {days_diff}) 상세 생성 완료", "day": days_diff}
        else:
            raise HTTPException(status_code=500, detail="상세 생성 실패")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/items/{roadmap_item_id}")
async def update_roadmap_item(roadmap_item_id: str, request: UpdateRoadmapItemRequest):
    """로드맵 항목의 완료 상태 업데이트"""
    try:
        parts = roadmap_item_id.split(":")
        
        if len(parts) == 3:
            # 새 구조: roadmap_id:day_index:task_index
            roadmap_id_str, day_index_str, task_index_str = parts
            try:
                try:
                    roadmap_id = ObjectId(roadmap_id_str)
                except (InvalidId, ValueError, TypeError):
                    roadmap_id = roadmap_id_str
                day_index = int(day_index_str)
                task_index = int(task_index_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"잘못된 인덱스 형식입니다")
            
            roadmaps_collection = await get_collection("roadmaps")
            roadmap = await roadmaps_collection.find_one({"_id": roadmap_id})
            if not roadmap:
                raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다.")
            
            items = roadmap.get("items", [])
            if day_index >= len(items):
                raise HTTPException(status_code=404, detail="로드맵 일차를 찾을 수 없습니다.")
            
            tasks = items[day_index].get("tasks", [])
            if task_index >= len(tasks):
                raise HTTPException(status_code=404, detail="해당 과업을 찾을 수 없습니다.")
            
            update_data = {
                "is_completed": 1 if request.is_completed else 0,
                "completed_at": datetime.utcnow() if request.is_completed else None
            }
            
            await roadmaps_collection.update_one(
                {"_id": roadmap_id},
                {
                    "$set": {
                        f"items.{day_index}.tasks.{task_index}.is_completed": update_data["is_completed"],
                        f"items.{day_index}.tasks.{task_index}.completed_at": update_data["completed_at"],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
        elif len(parts) == 2:
            # 레거시 구조: roadmap_id:item_index
            roadmap_id_str, item_index_str = parts
            try:
                try:
                    roadmap_id = ObjectId(roadmap_id_str)
                except (InvalidId, ValueError, TypeError):
                    roadmap_id = roadmap_id_str
                item_index = int(item_index_str)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"잘못된 item_index 형식입니다: {item_index_str}")
            
            roadmaps_collection = await get_collection("roadmaps")
            roadmap = await roadmaps_collection.find_one({"_id": roadmap_id})
            if not roadmap:
                raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다.")
            
            items = roadmap.get("items", [])
            if item_index >= len(items):
                raise HTTPException(status_code=404, detail="로드맵 항목을 찾을 수 없습니다.")
            
            update_data = {
                "is_completed": 1 if request.is_completed else 0,
                "completed_at": datetime.utcnow() if request.is_completed else None
            }
            
            await roadmaps_collection.update_one(
                {"_id": roadmap_id},
                {
                    "$set": {
                        f"items.{item_index}.is_completed": update_data["is_completed"],
                        f"items.{item_index}.completed_at": update_data["completed_at"],
                        "updated_at": datetime.utcnow()
                    }
                }
            )
        else:
            raise HTTPException(status_code=400, detail="잘못된 roadmap_item_id 형식입니다. 'roadmap_id:day_index:task_index' 또는 'roadmap_id:item_index' 형식이어야 합니다.")
        
        response_data = {
            "is_completed": update_data["is_completed"] == 1,
            "completed_at": update_data["completed_at"].isoformat() if update_data["completed_at"] else None
        }
        
        if len(parts) == 3:
            response_data["day_index"] = day_index
            response_data["task_index"] = task_index
        else:
            response_data["item_index"] = item_index
            
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로드맵 항목 업데이트 중 오류 발생: {str(e)}")


@router.post("/{roadmap_id}/extract-keywords")
async def extract_keywords_for_roadmap(roadmap_id: str):
    """기존 로드맵에 대해 키워드 추출 및 통계 업데이트"""
    try:
        roadmaps_collection = await get_collection("roadmaps")
        
        try:
            object_id = ObjectId(roadmap_id)
            roadmap = await roadmaps_collection.find_one({"_id": object_id})
        except (InvalidId, ValueError, TypeError):
            roadmap = await roadmaps_collection.find_one({"_id": roadmap_id})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
        
        user_id = roadmap.get("user_id")
        
        # 키워드 추출 및 저장
        await extract_and_save_keywords(roadmap, user_id)
        
        return {"status": "success", "message": "키워드 추출 및 저장 완료"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"키워드 추출 중 오류 발생: {str(e)}")
