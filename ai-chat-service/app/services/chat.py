
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
import numpy as np

from app.db.mongodb import get_collection
from app.db.vector import vector_store, embeddings
from app.services.session import get_session_config
from app.core.prompts import ROADMAP_QA_SYSTEM_PROMPT, ROADMAP_SYSTEM_PROMPT

def generate_embedding(text: str) -> Optional[List[float]]:
    """텍스트를 벡터 임베딩으로 변환 (LangChain 사용)"""
    try:
        if embeddings is None:
            print("⚠️ 임베딩 모델이 초기화되지 않았습니다.")
            return None
        
        # LangChain을 사용하여 임베딩 생성
        embedding = embeddings.embed_query(text)
        
        if embedding and len(embedding) > 0:
            return embedding
        else:
            return None
    except Exception as e:
        print(f"⚠️ 임베딩 생성 실패: {e}")
        import traceback
        traceback.print_exc()
        return None


async def save_conversation_message(
    session_id: str,
    role: str,
    content: str,
    user_id: Optional[str] = None
) -> Optional[Dict]:
    """대화 메시지를 개별 문서로 저장 (embedding 포함)"""
    try:
        conversation_messages = await get_collection("conversation_messages")
        now = datetime.utcnow()
        
        # 임베딩 생성 (백그라운드에서 처리)
        embedding = None
        try:
            # 동기 함수를 비동기로 실행
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(
                None,
                generate_embedding,
                content
            )
        except Exception as e:
            print(f"⚠️ 임베딩 생성 실패 (메시지는 저장됨): {e}")
        
        # 메시지 문서 생성
        message_doc = {
            "session_id": session_id,
            "user_id": user_id,
            "role": role,
            "content": content,
            "embedding": embedding,  # Vector Store와 동일 컬렉션 사용
            "created_at": now
        }
        
        # MongoDB에 저장 (embedding 포함)
        result = await conversation_messages.insert_one(message_doc)
        
        # Vector Store는 conversation_messages 컬렉션을 직접 사용하므로
        # 별도로 추가할 필요 없음 (MongoDB Atlas Vector Search가 자동으로 인덱싱)
        # 단, embedding이 없으면 Vector Store에 추가 (LangChain이 자동 생성)
        if vector_store and not embedding:
            try:
                from langchain_core.documents import Document
                doc = Document(
                    page_content=content,
                    metadata={
                        "session_id": session_id,
                        "user_id": user_id or "",
                        "role": role,
                        "created_at": now.isoformat()
                    }
                )
                # 비동기로 Vector Store에 추가 (embedding 자동 생성)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    vector_store.add_documents,
                    [doc]
                )
            except Exception as e:
                print(f"⚠️ Vector Store 추가 실패 (메시지는 저장됨): {e}")
        
        return {
            "session_id": session_id,
            "message_id": str(result.inserted_id),
            "role": role,
            "content": content,
            "created_at": now.isoformat()
        }
    except Exception as e:
        print(f"⚠️ 메시지 저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_conversation_messages(session_id: str, limit: int = 50) -> List[Dict]:
    """세션의 대화 메시지들 조회 (최근 N개) - MongoDB에서 개별 문서 조회"""
    try:
        conversation_messages = await get_collection("conversation_messages")
        
        # 세션별 메시지 조회 (최근 순으로 정렬)
        cursor = conversation_messages.find(
            {"session_id": session_id}
        ).sort("created_at", 1).limit(limit)  # 오래된 것부터 최근 순
        
        messages = await cursor.to_list(length=limit)
        
        # embedding 필드는 제외하고 반환
        result = []
        for msg in messages:
            result.append({
                "role": msg.get("role"),
                "content": msg.get("content"),
                "created_at": msg.get("created_at"),
                "session_id": msg.get("session_id"),
                "user_id": msg.get("user_id")
            })
        
        return result
    except Exception as e:
        print(f"⚠️ 대화 조회 실패: {e}")
        return []


async def get_conversation_by_session(session_id: str) -> Optional[Dict]:
    """세션 전체 정보 조회 (메시지 개수 등)"""
    try:
        conversation_messages = await get_collection("conversation_messages")
        
        # 세션별 메시지 개수 조회
        message_count = await conversation_messages.count_documents({"session_id": session_id})
        
        # 첫 메시지와 마지막 메시지 조회
        first_msg = await conversation_messages.find_one(
            {"session_id": session_id},
            sort=[("created_at", 1)]
        )
        last_msg = await conversation_messages.find_one(
            {"session_id": session_id},
            sort=[("created_at", -1)]
        )
        
        return {
            "session_id": session_id,
            "message_count": message_count,
            "created_at": first_msg.get("created_at") if first_msg else None,
            "updated_at": last_msg.get("created_at") if last_msg else None,
            "user_id": first_msg.get("user_id") if first_msg else None
        }
    except Exception as e:
        print(f"⚠️ 세션 조회 실패: {e}")
        return None



# 런타임 플래그: 벡터 검색 가능 여부
# 로컬 MongoDB 등 $vectorSearch를 지원하지 않는 환경에서 에러 로그 스팸 방지
VECTOR_SEARCH_AVAILABLE = True
USE_FALLBACK_SEARCH = False  # 로컬 폴백 검색 사용 여부

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """두 벡터 간의 코사인 유사도 계산"""
    try:
        vec1_array = np.array(vec1)
        vec2_array = np.array(vec2)
        
        # 차원 불일치 체크
        if len(vec1_array) != len(vec2_array):
            # 차원이 다른 경우 0 반환 (조용히 처리)
            return 0.0
        
        # 정규화
        norm1 = np.linalg.norm(vec1_array)
        norm2 = np.linalg.norm(vec2_array)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        dot_product = np.dot(vec1_array, vec2_array)
        return float(dot_product / (norm1 * norm2))
    except Exception as e:
        # 차원 불일치 등 에러는 조용히 0 반환
        return 0.0


async def search_similar_messages_fallback(query: str, user_id: Optional[str] = None, limit: int = 5) -> List[Dict]:
    """로컬 MongoDB에서 애플리케이션 레벨 벡터 검색 (폴백)"""
    try:
        if embeddings is None:
            return []
        
        # 쿼리 텍스트의 임베딩 생성
        loop = asyncio.get_event_loop()
        query_embedding = await loop.run_in_executor(
            None,
            embeddings.embed_query,
            query
        )
        
        if not query_embedding:
            return []
        
        # MongoDB에서 embedding이 있는 메시지 조회
        conversation_messages = await get_collection("conversation_messages")
        
        # 필터 조건 생성
        filter_dict = {"embedding": {"$exists": True, "$ne": None}}
        if user_id:
            filter_dict["user_id"] = user_id
        
        # 모든 메시지 조회 (embedding이 있는 것만)
        cursor = conversation_messages.find(filter_dict)
        messages = await cursor.to_list(length=10000)  # 최대 10000개 (성능 고려)
        
        if not messages:
            return []
        
        # 각 메시지와 쿼리의 코사인 유사도 계산
        similarities = []
        query_dim = len(query_embedding)
        skipped_count = 0
        
        for msg in messages:
            msg_embedding = msg.get("embedding")
            if not msg_embedding or not isinstance(msg_embedding, list):
                continue
            
            # 차원 불일치 체크 (다른 모델로 생성된 임베딩 스킵)
            if len(msg_embedding) != query_dim:
                skipped_count += 1
                continue
            
            similarity = cosine_similarity(query_embedding, msg_embedding)
            if similarity > 0:  # 유효한 유사도만 추가
                similarities.append({
                    "content": msg.get("content", ""),
                    "role": msg.get("role", ""),
                    "session_id": msg.get("session_id", ""),
                    "user_id": msg.get("user_id", ""),
                    "similarity": similarity,
                    "created_at": msg.get("created_at")
                })
        
        if skipped_count > 0:
            print(f"ℹ️ {skipped_count}개의 메시지는 다른 임베딩 모델로 생성되어 검색에서 제외되었습니다.")
        
        # 유사도가 높은 순으로 정렬하고 상위 N개 반환
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:limit]
        
    except Exception as e:
        print(f"⚠️ 폴백 벡터 검색 실패: {e}")
        import traceback
        traceback.print_exc()
        return []


async def search_similar_messages(query: str, user_id: Optional[str] = None, limit: int = 5) -> List[Dict]:
    """LangChain Vector Store에서 유사한 메시지 검색 (Atlas 지원 시) 또는 폴백 검색"""
    global VECTOR_SEARCH_AVAILABLE, USE_FALLBACK_SEARCH
    
    # 폴백 검색을 사용하는 경우
    if USE_FALLBACK_SEARCH:
        return await search_similar_messages_fallback(query, user_id, limit)
    
    if not VECTOR_SEARCH_AVAILABLE:
        # VECTOR_SEARCH_AVAILABLE이 False면 폴백 검색 사용
        USE_FALLBACK_SEARCH = True
        return await search_similar_messages_fallback(query, user_id, limit)

    try:
        if vector_store is None:
            # 초기화 실패 시 폴백 검색 시도
            USE_FALLBACK_SEARCH = True
            print("ℹ️ Vector Store가 없습니다. 폴백 검색을 사용합니다.")
            return await search_similar_messages_fallback(query, user_id, limit)
        
        # 필터 조건 생성 (user_id가 있을 때만)
        filter_dict = None
        if user_id:
            filter_dict = {"user_id": user_id}
        
        # 유사도 검색 (with_score=True로 점수도 반환)
        # LangChain Vector Store의 similarity_search_with_score는 동기 함수
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None,
            lambda: vector_store.similarity_search_with_score(
                query=query,
                k=limit,
                pre_filter=filter_dict
            )
        )
        
        # 결과 포맷팅
        formatted = []
        for doc, score in results:
            formatted.append({
                "content": doc.page_content,
                "role": doc.metadata.get("role", ""),
                "session_id": doc.metadata.get("session_id", ""),
                "user_id": doc.metadata.get("user_id", ""),
                "similarity": float(score),
                "created_at": doc.metadata.get("created_at", "")
            })
        
        return formatted
    except Exception as e:
        error_msg = str(e)
        if "$vectorSearch" in error_msg:
            print(f"ℹ️ 로컬 MongoDB는 Atlas Vector Search를 지원하지 않습니다. 폴백 검색을 사용합니다.")
            VECTOR_SEARCH_AVAILABLE = False
            USE_FALLBACK_SEARCH = True
            # 폴백 검색 시도
            return await search_similar_messages_fallback(query, user_id, limit)
        else:
            print(f"⚠️ Vector 검색 실패: {e}")
            # 실패 시에도 폴백 검색 시도
            USE_FALLBACK_SEARCH = True
            return await search_similar_messages_fallback(query, user_id, limit)


async def get_rag_context(query: str, session_id: str, user_id: Optional[str] = None, limit: int = 5) -> str:
    """RAG를 위한 관련 대화 컨텍스트 가져오기 (LangChain Vector Search 사용)"""
    try:
        # LangChain Vector Store로 유사 메시지 검색
        similar_messages = await search_similar_messages(
            query=query,
            user_id=user_id,
            limit=limit
        )
        
        if not similar_messages:
            return ""
        
        # 컨텍스트 포맷팅
        context_parts = []
        for msg in similar_messages:
            role = msg.get("role", "")
            if role == "user":
                role_label = "사용자"
            elif role == "assistant":
                role_label = "어시스턴트"
            else:
                role_label = role
            content = msg.get("content", "")
            similarity = msg.get("similarity", 0)
            context_parts.append(f"[{role_label}] (유사도: {similarity:.2f}): {content}")
        
        context = "\n".join(context_parts)
        return f"\n\n[관련 과거 대화 내용]\n{context}\n\n위의 과거 대화 내용을 참고하여 현재 질문에 답변해주세요."
    except Exception as e:
        print(f"⚠️ RAG 컨텍스트 생성 실패: {e}")
        return ""


async def get_system_prompt(session_id: str, rag_context: str = "") -> str:
    """세션에 맞는 시스템 프롬프트 가져오기"""
    config = await get_session_config(session_id)
    
    # 로드맵 모드인 경우
    if config and config.get("mode") == "roadmap":
        return ROADMAP_SYSTEM_PROMPT
    
    if config and config.get("mode") == "qa":
        return ROADMAP_QA_SYSTEM_PROMPT

    # 성격이 선택된 경우
    base_prompt = None
    if config and config.get("personality_id"):
        personalities = await get_collection("personalities")
        personality = await personalities.find_one({"_id": config["personality_id"]})
        if personality:
            base_prompt = personality.get("system_prompt")
    
    # 기본값: 베타인 (첫 번째 성격)
    if not base_prompt:
        personalities = await get_collection("personalities")
        default_personality = await personalities.find_one({"name": "베타인"})
        if default_personality:
            base_prompt = default_personality.get("system_prompt")
        else:
            base_prompt = "당신은 도움이 되는 AI 어시스턴트입니다."
    
    # RAG 컨텍스트 추가 (로드맵 모드가 아닐 때만)
    if rag_context:
        base_prompt += rag_context
    
    return base_prompt
