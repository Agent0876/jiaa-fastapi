
from typing import Optional, List, Dict
from datetime import datetime
import json
import asyncio
import os
import uuid
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends
from langchain_core.documents import Document

from app.core.config import settings
from app.core.prompts import ROADMAP_QA_SYSTEM_PROMPT
from app.db.mongodb import get_collection
from app.services.bedrock import bedrock_runtime
from app.services.chat import (
    save_conversation_message,
    get_conversation_messages,
    search_similar_messages,
    get_rag_context,
    get_system_prompt
)
from app.services.session import get_session_config
from app.services.roadmap import (
    generate_full_roadmap,
    save_roadmap,
    generate_day_details
)
from app.models.chat import ChatRequest, ChatResponse, SearchRequest, SaveMessageRequest
from app.models.roadmap import StartRoadmapRequest
from app.api.deps import get_user_id_from_token

router = APIRouter()
active_connections: Dict[str, WebSocket] = {}

@router.post("/roadmap/start")
async def start_roadmap(request: StartRoadmapRequest):
    """로드맵 생성 모드 시작"""
    try:
        session_configs = await get_collection("session_configs")
        config = await session_configs.find_one({"session_id": request.session_id})
        
        update_data = {
            "mode": "roadmap",
            "updated_at": datetime.utcnow()
        }
        
        if request.user_id:
            update_data["user_id"] = request.user_id
        
        if not config:
            config_doc = {
                "session_id": request.session_id,
                "user_id": request.user_id,
                "personality_id": None,
                "mode": "roadmap",
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await session_configs.insert_one(config_doc)
        else:
            await session_configs.update_one(
                {"session_id": request.session_id},
                {"$set": update_data}
            )
        
        return {
            "message": "로드맵 생성 모드가 시작되었습니다.",
            "session_id": request.session_id,
            "mode": "roadmap"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"로드맵 모드 시작 중 오류 발생: {str(e)}")


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest, 
    user_id_from_token: Optional[str] = Depends(get_user_id_from_token)
):
    """Bedrock을 사용한 채팅 엔드포인트"""
    try:
        session_id = request.session_id
        if not session_id:
            session_id = str(uuid.uuid4())
        
        user_id = user_id_from_token or request.user_id
        print(f"🔍 [Chat Debug] 최종 user_id: {user_id} (JWT: {user_id_from_token}, Request: {request.user_id})")
        
        config = await get_session_config(session_id)
        if user_id:
            try:
                session_configs = await get_collection("session_configs")
                if not config:
                    config_doc = {
                        "session_id": session_id,
                        "user_id": user_id,
                        "mode": "chat",
                        "personality_id": None,
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                    await session_configs.insert_one(config_doc)
                    config = config_doc
                elif not config.get("user_id"):
                    await session_configs.update_one(
                        {"session_id": session_id},
                        {"$set": {"user_id": user_id, "updated_at": datetime.utcnow()}}
                    )
                    config["user_id"] = user_id
            except ValueError:
                pass
        
        if not config:
            config = await get_session_config(session_id)
        
        if config and config.get("mode") == "roadmap":
            model_id = settings.ROADMAP_MODEL_ID
            print(f"📋 [Chat] 로드맵 모드 - 모델 ID: {model_id}")
            rag_context = ""
        elif request.message.startswith("[오늘 로드맵 질문]"):
            model_id = settings.ROADMAP_MODEL_ID
            rag_context = ""
            print(f"📚 [Chat] 로드맵 질문 감지됨 - 모델 ID: {model_id}")
        else:
            model_id = request.model_id or settings.DEFAULT_MODEL_ID
            print(f"💬 [Chat] 일반 채팅 모드 - 모델 ID: {model_id}")
            try:
                rag_context = await get_rag_context(
                    query=request.message,
                    session_id=session_id,
                    user_id=user_id,
                    limit=5
                )
            except Exception as rag_error:
                print(f"⚠️ [Chat] RAG 컨텍스트 생성 실패 (계속 진행): {rag_error}")
                rag_context = ""
        
        if request.message.startswith("[오늘 로드맵 질문]"):
            system_prompt = ROADMAP_QA_SYSTEM_PROMPT
        else:
            system_prompt = await get_system_prompt(session_id, rag_context=rag_context)
        
        messages = []
        if request.conversation_history:
            for msg in request.conversation_history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
        else:
            stored_messages = await get_conversation_messages(session_id, limit=50)
            for msg in stored_messages:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
        
        messages.append({
            "role": "user",
            "content": request.message,
        })
        
        user_id_for_save = None
        if config and config.get("user_id"):
            user_id_for_save = str(config["user_id"])
        elif user_id:
            user_id_for_save = user_id
        elif request.user_id:
            user_id_for_save = request.user_id
        
        asyncio.create_task(save_conversation_message(
            session_id=session_id,
            role="user",
            content=request.message,
            user_id=user_id_for_save
        ))
        
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "system": system_prompt,
                "messages": messages,
            }
        )

        try:
            response = bedrock_runtime.invoke_model(
                modelId=model_id,
                body=body,
            )
        except Exception as bedrock_error:
            print(f"❌ [Chat] Bedrock API 호출 실패: {bedrock_error}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Bedrock API 호출 실패: {str(bedrock_error)}"
            )

        try:
            response_body = json.loads(response.get("body").read())
            assistant_message = response_body.get("content", [])[0].get("text", "")
        except Exception as parse_error:
            print(f"❌ [Chat] Bedrock 응답 파싱 실패: {parse_error}")
            import traceback
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Bedrock 응답 파싱 실패: {str(parse_error)}"
            )
        
        if config and config.get("mode") == "roadmap":
            print(f"🔍 [Roadmap] 로드맵 모드 감지됨. JSON 처리 중...")
            
            json_str = None
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', assistant_message)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'```\s*([\s\S]*?)\s*```', assistant_message)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    roadmap_start = assistant_message.find('"roadmap"')
                    if roadmap_start != -1:
                        brace_start = assistant_message.rfind('{', 0, roadmap_start)
                        if brace_start != -1:
                             json_str = assistant_message[brace_start:]
                             last_brace = json_str.rfind('}')
                             if last_brace != -1:
                                 json_str = json_str[:last_brace+1]
            
            if json_str:
                try:
                    json_str = json_str.strip()
                    json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
                    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                    json_str = re.sub(r'\n\s*\n', '\n', json_str)
                    json_str = json_str.strip()
                    
                    roadmap_data = json.loads(json_str)
                    
                    if roadmap_data.get("roadmap") and isinstance(roadmap_data.get("roadmap"), list):
                        if not user_id_for_save:
                            if config and config.get("user_id"):
                                user_id_for_save = str(config["user_id"])
                            elif user_id:
                                user_id_for_save = user_id
                            elif request.user_id:
                                user_id_for_save = request.user_id
                        
                        total_days = roadmap_data.get("total_days", 0)
                        current_items = len(roadmap_data.get("roadmap", []))
                        
                        if total_days > current_items and total_days > 30:
                            print(f"🔄 [Roadmap] 배치 생성 필요")
                            full_roadmap = await generate_full_roadmap(
                                roadmap_info=roadmap_data,
                                session_id=session_id,
                                user_id=user_id_for_save
                            )
                            if full_roadmap:
                                roadmap_data = full_roadmap
                        
                        result = await save_roadmap(roadmap_data, session_id, user_id_for_save)
                        
                        if result:
                            roadmap_id = str(result.get('_id'))
                            goal = roadmap_data.get('name', '학습')
                            asyncio.create_task(generate_day_details(roadmap_id, 1, goal))
                            
                            roadmap_name = roadmap_data.get('name', '로드맵')
                            total_items = len(roadmap_data.get('roadmap', []))
                            assistant_message = f"✅ 로드맵 '{roadmap_name}'이 생성되었습니다! ({total_items}일) 로드맵 목록에서 확인하실 수 있습니다."
                except Exception as e:
                    print(f"❌ [Roadmap] 로드맵 처리 중 오류: {e}")
        
        asyncio.create_task(save_conversation_message(
            session_id=session_id,
            role="assistant",
            content=assistant_message,
            user_id=user_id_for_save
        ))
        
        return ChatResponse(
            response=assistant_message,
            model_id=model_id,
            session_id=session_id,
        )

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"❌ [Chat Error] 오류 발생: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"채팅 처리 중 오류 발생: {str(e)}"
        )


@router.post("/clear")
async def clear_history(session_id: str):
    """특정 세션의 대화 히스토리 삭제"""
    try:
        conversation_messages = await get_collection("conversation_messages")
        result = await conversation_messages.delete_many({"session_id": session_id})
        return {
            "message": f"대화 히스토리가 삭제되었습니다. ({result.deleted_count}개 메시지 삭제)",
            "session_id": session_id,
            "deleted_count": result.deleted_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"히스토리 삭제 중 오류 발생: {str(e)}")


@router.post("/search")
async def search_conversations(request: SearchRequest):
    """벡터 검색을 사용한 대화 메시지 검색"""
    try:
        results = await search_similar_messages(
            query=request.query,
            user_id=request.user_id,
            limit=request.limit or 5
        )
        
        return {
            "query": request.query,
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 중 오류 발생: {str(e)}")


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    limit: int = 100,
    user_id: Optional[str] = Depends(get_user_id_from_token)
):
    """세션별 메시지 목록 조회"""
    try:
        messages = await get_conversation_messages(session_id, limit=limit)
        return {
            "session_id": session_id,
            "messages": messages,
            "count": len(messages)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"메시지 조회 중 오류 발생: {str(e)}")


@router.post("/sessions/{session_id}/messages")
async def save_session_message(
    session_id: str,
    request: SaveMessageRequest,
    user_id: Optional[str] = Depends(get_user_id_from_token)
):
    """세션에 메시지 저장"""
    try:
        result = await save_conversation_message(
            session_id=session_id,
            role=request.role,
            content=request.content,
            user_id=user_id
        )
        if result:
            return result
        else:
            raise HTTPException(status_code=500, detail="메시지 저장 실패")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"메시지 저장 중 오류 발생: {str(e)}")


@router.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 기반 채팅 엔드포인트"""
    await websocket.accept()
    session_id = None
    
    try:
        while True:
            data = await websocket.receive_text()
            
            try:
                request_data = json.loads(data)
                message = request_data.get("message", "")
                
                if not message:
                    await websocket.send_json({"type": "error", "error": "메시지가 비어있습니다."})
                    continue
                
                session_id = request_data.get("session_id")
                if not session_id:
                    session_id = str(uuid.uuid4())
                    await websocket.send_json({"type": "session", "session_id": session_id})
                
                active_connections[session_id] = websocket
                
                user_id_from_token = None
                token = request_data.get("token") or request_data.get("authorization")
                if token:
                    if token.startswith("Bearer "):
                        token = token.replace("Bearer ", "").strip()
                    try:
                        jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
                        import base64
                        parts = token.split('.')
                        if len(parts) == 3:
                            payload = parts[1]
                            payload += '=' * (4 - len(payload) % 4)
                            decoded = json.loads(base64.urlsafe_b64decode(payload))
                            user_id_from_token = decoded.get("user_id") or decoded.get("sub")
                    except Exception as e:
                        print(f"⚠️ [WebSocket Debug] JWT 파싱 실패: {e}")
                
                config = await get_session_config(session_id)
                user_id = request_data.get("user_id") or user_id_from_token
                
                if not config and (user_id or session_id):
                    session_configs = await get_collection("session_configs")
                    config_doc = {
                        "session_id": session_id,
                        "user_id": user_id,
                        "mode": "chat",
                        "created_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                    await session_configs.insert_one(config_doc)
                    config = config_doc

                user_id_for_save = None
                if config and config.get("user_id"):
                    user_id_for_save = str(config["user_id"])
                elif user_id:
                    user_id_for_save = user_id
                
                if config and config.get("mode") == "roadmap":
                    model_id = settings.ROADMAP_MODEL_ID
                    rag_context = ""
                elif message.startswith("[오늘 로드맵 질문]"):
                    model_id = settings.ROADMAP_MODEL_ID
                    rag_context = ""
                else:
                    model_id = request_data.get("model_id", settings.DEFAULT_MODEL_ID)
                    try:
                        rag_context = await get_rag_context(
                            query=message,
                            session_id=session_id,
                            user_id=user_id_for_save,
                            limit=5
                        )
                    except:
                        rag_context = ""
                
                max_tokens = request_data.get("max_tokens", 4096)
                temperature = request_data.get("temperature", 0.7)
                
                if message.startswith("[오늘 로드맵 질문]"):
                    system_prompt = ROADMAP_QA_SYSTEM_PROMPT
                else:
                    system_prompt = await get_system_prompt(session_id, rag_context=rag_context)
                
                messages = []
                if request_data.get("conversation_history"):
                    for msg in request_data["conversation_history"]:
                        if isinstance(msg, dict) and "role" in msg and "content" in msg:
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })
                else:
                    stored_messages = await get_conversation_messages(session_id, limit=50)
                    for msg in stored_messages:
                        if isinstance(msg, dict) and "role" in msg and "content" in msg:
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })
                
                messages.append({
                    "role": "user",
                    "content": message,
                })
                
                asyncio.create_task(save_conversation_message(
                    session_id=session_id,
                    role="user",
                    content=message,
                    user_id=user_id_for_save
                ))
                
                body = json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": system_prompt,
                        "messages": messages,
                    }
                )
                
                response = bedrock_runtime.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=body,
                )
                
                assistant_message = ""
                stream = response.get('body')
                
                if stream:
                    for event in stream:
                        if 'chunk' in event:
                            chunk_data = event['chunk']
                            if 'bytes' in chunk_data:
                                chunk = json.loads(chunk_data['bytes'].decode())
                            else:
                                chunk = chunk_data
                            
                            if 'delta' in chunk and 'text' in chunk['delta']:
                                text_chunk = chunk['delta']['text']
                                assistant_message += text_chunk
                                await websocket.send_json({
                                    "type": "chunk",
                                    "text": text_chunk,
                                    "session_id": session_id,
                                })
                
                if assistant_message:
                    if config and config.get("mode") == "roadmap":
                        # JSON 처리 로직 (간소화)
                        json_str = None
                        if "```json" in assistant_message:
                            parts = assistant_message.split("```json")
                            if len(parts) > 1:
                                json_part = parts[1].split("```")[0]
                                json_str = json_part
                        
                        if json_str:
                            try:
                                json_str = json_str.strip()
                                json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
                                roadmap_data = json.loads(json_str)

                                if roadmap_data.get("roadmap"):
                                    if not user_id_for_save:
                                         if config and config.get("user_id"):
                                             user_id_for_save = str(config["user_id"])
                                    
                                    # 배치 처리 및 저장
                                    total_days = roadmap_data.get("total_days", 0)
                                    current_items = len(roadmap_data.get("roadmap", []))
                                    if total_days > current_items and total_days > 30:
                                        full = await generate_full_roadmap(roadmap_data, session_id, user_id_for_save)
                                        if full: roadmap_data = full
                                    
                                    res = await save_roadmap(roadmap_data, session_id, user_id_for_save)
                                    if res:
                                        # 상세 생성
                                        asyncio.create_task(generate_day_details(str(res.get('_id')), 1, roadmap_data.get('name', '학습')))
                            except:
                                pass

                    asyncio.create_task(save_conversation_message(
                        session_id=session_id,
                        role="assistant",
                        content=assistant_message,
                        user_id=user_id_for_save
                    ))
                    
                    await websocket.send_json({
                        "type": "message",
                        "response": assistant_message,
                        "model_id": model_id,
                        "session_id": session_id,
                    })
                
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "error": "잘못된 JSON 형식입니다."})
            except Exception as e:
                await websocket.send_json({"type": "error", "error": f"오류 발생: {str(e)}"})
                
    except WebSocketDisconnect:
        if session_id and session_id in active_connections:
            del active_connections[session_id]
    except Exception as e:
        if session_id and session_id in active_connections:
            del active_connections[session_id]
