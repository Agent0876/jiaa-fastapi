
import json
import asyncio
import re
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from bson import ObjectId

from app.core.config import settings
from app.core.prompts import (
    ROADMAP_BATCH_PROMPT,
    ROADMAP_PLAN_PROMPT,
    TASK_DETAIL_PROMPT
)
from app.services.bedrock import bedrock_runtime
from app.db.mongodb import get_collection


def parse_roadmap_json(text: str) -> Optional[Dict]:
    """응답 텍스트에서 로드맵 JSON을 파싱"""
    try:
        # JSON 블록 찾기 (```json ... ``` 또는 {...})
        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', text)
        if not json_match:
            # 직접 JSON 객체 찾기
            json_match = re.search(r'\{[\s\S]*"roadmap"[\s\S]*\}', text)
        
        if json_match:
            json_str = json_match.group(1) if json_match.lastindex else json_match.group(0)
            parsed = json.loads(json_str)
            if parsed.get("roadmap") and isinstance(parsed.get("roadmap"), list):
                return parsed
    except Exception as e:
        print(f"⚠️ 로드맵 JSON 파싱 실패: {e}")
    return None


async def generate_roadmap_batch(
    start_day: int,
    end_day: int,
    context: Dict,
    model_id: str = settings.DEFAULT_MODEL_ID
) -> List[Dict]:
    """7일 단위로 로드맵 배치 생성 (키워드 기반)"""
    try:
        print(f"🔄 [Batch] Day {start_day} ~ Day {end_day} 생성 중...")
        
        # 배치 프롬프트 생성
        prompt = ROADMAP_BATCH_PROMPT.format(
            start_day=start_day,
            end_day=end_day,
            goal=context.get("goal", ""),
            total_days=context.get("total_days", 90),
            daily_time=context.get("daily_time", "6시간"),
            week_keywords=context.get("week_keywords", "학습")
        )
        
        # Bedrock API 호출
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "temperature": 0.7,
            "system": "당신은 학습 로드맵을 생성하는 AI입니다. 지시된 범위의 일차만 정확하게 JSON으로 출력합니다.",
            "messages": [{"role": "user", "content": prompt}]
        })
        
        # 비동기 실행을 위해 run_in_executor 사용
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=model_id,
                body=body
            )
        )
        
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])
        if content and len(content) > 0:
            response_text = content[0].get("text", "")
        else:
            print(f"❌ [Batch] 응답이 비어있음")
            return []
        
        # JSON 파싱
        response_text = re.sub(r'//.*?$', '', response_text, flags=re.MULTILINE)
        response_text = re.sub(r'/\*.*?\*/', '', response_text, flags=re.DOTALL)
        
        json_match = re.search(r'\{[\s\S]*"batch"[\s\S]*\}', response_text)
        if json_match:
            batch_data = json.loads(json_match.group(0))
            batch_items = batch_data.get("batch", [])
            print(f"✅ [Batch] Day {start_day} ~ Day {end_day} 생성 완료: {len(batch_items)}일")
            return batch_items
        else:
            print(f"❌ [Batch] JSON 파싱 실패")
            return []
            
    except Exception as e:
        print(f"❌ [Batch] 배치 생성 오류: {e}")
        return []


async def generate_weekly_plan(
    goal: str,
    sub_goals: str,
    total_days: int,
    daily_time: str,
    model_id: str = settings.DEFAULT_MODEL_ID
) -> List[Dict]:
    """주차별 키워드 계획 생성"""
    try:
        total_weeks = (total_days + 6) // 7  # 올림
        print(f"📋 [Plan] {total_weeks}주 계획 생성 중...")
        
        prompt = ROADMAP_PLAN_PROMPT.format(
            goal=goal,
            sub_goals=sub_goals,
            total_days=total_days,
            total_weeks=total_weeks,
            daily_time=daily_time
        )
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "temperature": 0.7,
            "system": "당신은 학습 계획을 수립하는 AI입니다. 주차별 키워드를 JSON으로 출력합니다.",
            "messages": [{"role": "user", "content": prompt}]
        })
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(
                modelId=model_id,
                body=body
            )
        )
        
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])
        if content and len(content) > 0:
            response_text = content[0].get("text", "")
        else:
            return []
        
        response_text = re.sub(r'//.*?$', '', response_text, flags=re.MULTILINE)
        json_match = re.search(r'\{[\s\S]*"plan"[\s\S]*\}', response_text)
        if json_match:
            plan_data = json.loads(json_match.group(0))
            plan = plan_data.get("plan", [])
            print(f"✅ [Plan] {len(plan)}주 계획 생성 완료")
            return plan
        return []
    except Exception as e:
        print(f"❌ [Plan] 계획 생성 오류: {e}")
        return []


async def generate_task_details(
    goal: str,
    day: int,
    task_content: str,
    task_time: str,
    model_id: str = settings.DEFAULT_MODEL_ID
) -> Optional[Dict]:
    """단일 과업의 상세 내용 생성"""
    try:
        print(f"📝 [TaskDetail] Day {day} - '{task_content}' 상세 생성 중...")
        
        prompt = TASK_DETAIL_PROMPT.format(
            goal=goal,
            day=day,
            task_content=task_content,
            task_time=task_time
        )
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "temperature": 0.7,
            "system": "당신은 학습 콘텐츠를 상세하게 작성하는 AI입니다. JSON만 출력합니다.",
            "messages": [{"role": "user", "content": prompt}]
        })
        
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: bedrock_runtime.invoke_model(modelId=model_id, body=body)
        )
        
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])
        if content and len(content) > 0:
            response_text = content[0].get("text", "")
        else:
            return None
        
        response_text = re.sub(r'//.*?$', '', response_text, flags=re.MULTILINE)
        json_match = re.search(r'\{[\s\S]*"details"[\s\S]*\}', response_text)
        if json_match:
            detail_data = json.loads(json_match.group(0))
            details = detail_data.get("details", {})
            print(f"✅ [TaskDetail] Day {day} - '{task_content}' 상세 생성 완료")
            return details
        return None
    except Exception as e:
        print(f"❌ [TaskDetail] 상세 생성 오류: {e}")
        return None


async def generate_day_details(
    roadmap_id: str,
    day: int,
    goal: str
) -> bool:
    """특정 일차의 모든 과업에 대해 상세 내용 생성 후 DB 업데이트"""
    try:
        roadmaps = await get_collection("roadmaps")
        roadmap = await roadmaps.find_one({"_id": ObjectId(roadmap_id)})
        
        if not roadmap:
            print(f"❌ [DayDetail] 로드맵을 찾을 수 없음: {roadmap_id}")
            return False
        
        items = roadmap.get("items", [])
        
        # 해당 일차 찾기
        day_index = None
        day_item = None
        for idx, item in enumerate(items):
            if item.get("day") == day:
                day_index = idx
                day_item = item
                break
        
        if day_item is None:
            print(f"❌ [DayDetail] Day {day}를 찾을 수 없음")
            return False
        
        tasks = day_item.get("tasks", [])
        if not tasks:
            return False
        
        # 이미 상세가 있는지 확인
        if tasks[0].get("details"):
            print(f"⏭️ [DayDetail] Day {day} 이미 상세 있음, 건너뜀")
            return True
        
        print(f"📝 [DayDetail] Day {day} - {len(tasks)}개 과업 상세 생성 시작...")
        
        # 모든 과업에 대해 병렬로 상세 생성
        detail_tasks = [
            generate_task_details(
                goal=goal,
                day=day,
                task_content=task.get("content", ""),
                task_time=task.get("time", "1시간")
            )
            for task in tasks
        ]
        
        results = await asyncio.gather(*detail_tasks, return_exceptions=True)
        
        # 결과를 tasks에 적용
        updated_tasks = []
        for idx, task in enumerate(tasks):
            result = results[idx]
            if isinstance(result, dict):
                task["details"] = result
            else:
                # 실패 시 기본 상세
                task["details"] = {
                    "objectives": [f"{task.get('content', '')} 학습"],
                    "key_concepts": [],
                    "steps": [{"order": 1, "title": "학습", "description": task.get("content", ""), "duration": task.get("time", "1시간")}],
                    "resources": [],
                    "tips": ""
                }
            updated_tasks.append(task)
        
        # DB 업데이트
        await roadmaps.update_one(
            {"_id": ObjectId(roadmap_id)},
            {"$set": {f"items.{day_index}.tasks": updated_tasks}}
        )
        
        print(f"✅ [DayDetail] Day {day} 상세 생성 및 저장 완료")
        return True
        
    except Exception as e:
        print(f"❌ [DayDetail] Day {day} 상세 생성 오류: {e}")
        import traceback
        traceback.print_exc()
        return False


async def generate_full_roadmap(
    roadmap_info: Dict,
    session_id: str,
    user_id: Optional[str] = None
) -> Optional[Dict]:
    """전체 로드맵을 병렬로 생성 (주차별 키워드 기반)"""
    try:
        total_days = roadmap_info.get("total_days", 90)
        existing_items = roadmap_info.get("roadmap", [])
        goal = roadmap_info.get("name", "학습 목표")
        
        print(f"🚀 [FullRoadmap] 병렬 생성 시작: {total_days}일 (기존: {len(existing_items)}일)")
        
        # 1단계: 주차별 계획 생성
        weekly_plan = await generate_weekly_plan(
            goal=goal,
            sub_goals="",
            total_days=total_days,
            daily_time="6시간"
        )
        
        if not weekly_plan:
            # 계획 생성 실패 시 기본 계획 사용
            total_weeks = (total_days + 6) // 7
            weekly_plan = [{"week": i+1, "theme": f"Week {i+1}", "keywords": ["학습"]} for i in range(total_weeks)]
        
        # 2단계: 모든 주차를 병렬로 생성
        tasks = []
        for week_info in weekly_plan:
            week_num = week_info.get("week", 1)
            start_day = (week_num - 1) * 7 + 1
            end_day = min(week_num * 7, total_days)
            
            # 이미 생성된 일차는 건너뛰기
            existing_days = {item.get("day") for item in existing_items}
            if all(d in existing_days for d in range(start_day, end_day + 1)):
                continue
            
            keywords = ", ".join(week_info.get("keywords", ["학습"]))
            theme = week_info.get("theme", "")
            week_keywords = f"{theme}: {keywords}"
            
            context = {
                "goal": goal,
                "total_days": total_days,
                "daily_time": "6시간",
                "week_keywords": week_keywords
            }
            
            tasks.append(generate_roadmap_batch(start_day, end_day, context))
        
        print(f"🔀 [FullRoadmap] {len(tasks)}개 배치 병렬 실행 중...")
        
        # 병렬 실행
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 결과 합치기
        all_items = list(existing_items)
        for result in results:
            if isinstance(result, list):
                all_items.extend(result)
            elif isinstance(result, Exception):
                print(f"⚠️ [FullRoadmap] 배치 실패: {result}")
        
        # 누락된 일차 채우기 (더 나은 폴백)
        existing_days = {item.get("day") for item in all_items}
        missing_days = [day for day in range(1, total_days + 1) if day not in existing_days]
        
        if missing_days:
            # 누락된 일차 재생성 로직 (생략 - main.py에서 복사한다고 가정, 여기서 간소화 또는 동일 구현)
            # 구현 길어지므로 생략하지 않고 핵심 로직 포함
            retry_tasks = []
            for start_day in range(min(missing_days), max(missing_days) + 1, 7):
                end_day = min(start_day + 6, max(missing_days))
                week_num = (start_day - 1) // 7 + 1
                
                week_keywords = "학습"
                theme = ""
                for week_info in weekly_plan:
                    if week_info.get("week") == week_num:
                        keywords = ", ".join(week_info.get("keywords", ["학습"]))
                        theme = week_info.get("theme", "")
                        week_keywords = f"{theme}: {keywords}"
                        break
                
                context = {
                    "goal": goal,
                    "total_days": total_days,
                    "daily_time": "6시간",
                    "week_keywords": week_keywords
                }
                
                retry_tasks.append((start_day, end_day, context, week_keywords, theme))
            
            if retry_tasks:
                retry_results = await asyncio.gather(*[
                    generate_roadmap_batch(start_day, end_day, context, settings.ROADMAP_MODEL_ID)
                    for start_day, end_day, context, _, _ in retry_tasks
                ], return_exceptions=True)
                
                for idx, (start_day, end_day, context, week_keywords, theme) in enumerate(retry_tasks):
                    result = retry_results[idx]
                    if isinstance(result, list) and result:
                        all_items.extend(result)
                    else:
                        # 폴백
                        for day in range(start_day, end_day + 1):
                            if day not in {item.get("day") for item in all_items}:
                                all_items.append({
                                    "day": day,
                                    "tasks": [{"rank": 1, "content": f"{theme} 학습", "time": "1시간"}]
                                })
        
        all_items.sort(key=lambda x: x.get("day", 0))
        
        complete_roadmap = {
            "name": goal,
            "total_days": total_days,
            "roadmap": all_items
        }
        
        print(f"✅ [FullRoadmap] 병렬 생성 완료: {len(all_items)}일")
        return complete_roadmap
        
    except Exception as e:
        print(f"❌ [FullRoadmap] 전체 로드맵 생성 오류: {e}")
        import traceback
        traceback.print_exc()
        return None


def format_roadmap_for_rag(roadmap_data: Dict) -> str:
    """로드맵 데이터를 RAG용 텍스트로 변환"""
    roadmap_name = roadmap_data.get("name", "로드맵")
    roadmap_items = roadmap_data.get("roadmap", [])
    
    text_parts = [f"로드맵: {roadmap_name}"]
    
    for item in roadmap_items:
        day = item.get("day", "")
        tasks = item.get("tasks", [])
        
        if tasks:
            task_texts = []
            for task in tasks:
                content = task.get("content", "")
                time = task.get("time", "")
                task_texts.append(f"  - {content} ({time})")
            text_parts.append(f"일차 {day}:")
            text_parts.extend(task_texts)
        else:
            content = item.get("content", "")
            time = item.get("time", "")
            text_parts.append(f"일차 {day}: {content} (학습 시간: {time})")
    
    return "\n".join(text_parts)


async def save_roadmap(roadmap_data: Dict, session_id: str, user_id: Optional[str] = None) -> Optional[Dict]:
    """로드맵 데이터를 MongoDB에 저장"""
    try:
        roadmap_items = roadmap_data.get("roadmap", [])
        
        if not roadmap_items:
            return None
        
        first_item_created_at = None
        items = []
        
        for idx, item_data in enumerate(roadmap_items):
            # 날짜 계산
            if idx == 0 or item_data.get("day") == 1:
                item_created_at = datetime.utcnow()
                first_item_created_at = item_created_at
            else:
                if first_item_created_at:
                    days_to_add = item_data.get("day", 1) - 1
                    item_created_at = first_item_created_at + timedelta(days=days_to_add)
                else:
                    item_created_at = datetime.utcnow()
            
            tasks_data = item_data.get("tasks", [])
            if tasks_data:
                tasks = []
                for task in tasks_data:
                    tasks.append({
                        "rank": task.get("rank", 0),
                        "content": task.get("content", ""),
                        "time": task.get("time", ""),
                        "is_completed": 0,
                        "completed_at": None,
                        # details가 이미 있으면 유지
                        "details": task.get("details")
                    })
                
                items.append({
                    "day": item_data.get("day"),
                    "tasks": tasks,
                    "created_at": item_created_at
                })
            else:
                # 레거시
                items.append({
                    "day": item_data.get("day"),
                    "tasks": [{
                        "rank": 1,
                        "content": item_data.get("content", ""),
                        "time": item_data.get("time", ""),
                        "is_completed": 0,
                        "completed_at": None
                    }],
                    "created_at": item_created_at
                })
        
        roadmap_doc = {
            "name": roadmap_data.get("name"),
            "session_id": session_id,
            "user_id": user_id,
            "items": items,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        roadmaps = await get_collection("roadmaps")
        result = await roadmaps.insert_one(roadmap_doc)
        
        roadmap_doc["_id"] = str(result.inserted_id)
        return roadmap_doc
        
    except Exception as e:
        print(f"⚠️ 로드맵 저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return None
