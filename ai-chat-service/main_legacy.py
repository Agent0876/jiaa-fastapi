import asyncio
import json
import os
import uuid
from typing import Optional, List, Dict
from datetime import datetime, timedelta

import boto3
import numpy as np
import jwt
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_core.documents import Document
from pymongo import MongoClient

from database import init_db, get_collection, get_database, run_async

app = FastAPI()

# CORS 설정 (Electron 앱에서 접근 가능하도록)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 환경에서는 모든 origin 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 앱 시작 이벤트에서 데이터베이스 초기화
@app.on_event("startup")
async def startup_event():
    """앱 시작 시 데이터베이스 초기화 및 스케줄러 시작"""
    try:
        await init_db()
    except Exception as e:
        print(f"⚠️ 데이터베이스 초기화 중 오류 (무시 가능): {e}")
    
    # 자정 상세 생성 스케줄러 시작
    asyncio.create_task(midnight_detail_scheduler())


async def midnight_detail_scheduler():
    """매일 자정(KST)에 오늘 일차의 상세 내용 생성"""
    import pytz
    kst = pytz.timezone('Asia/Seoul')
    
    while True:
        try:
            # 현재 한국 시간
            now = datetime.now(kst)
            
            # 다음 자정까지 대기 시간 계산
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_seconds = (tomorrow - now).total_seconds()
            
            print(f"⏰ [Scheduler] 다음 상세 생성까지 {wait_seconds/3600:.1f}시간 대기...")
            await asyncio.sleep(wait_seconds)
            
            # 자정이 됐으니 모든 로드맵의 오늘 상세 생성
            print(f"🌙 [Scheduler] 자정 상세 생성 시작 - {datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S')}")
            await generate_all_today_details()
            
        except Exception as e:
            print(f"❌ [Scheduler] 스케줄러 오류: {e}")
            await asyncio.sleep(3600)  # 오류 시 1시간 후 재시도


async def generate_all_today_details():
    """모든 활성 로드맵의 오늘 일차 상세 생성"""
    try:
        roadmaps = await get_collection("roadmaps")
        cursor = roadmaps.find({})
        roadmap_list = await cursor.to_list(length=None)
        
        print(f"📋 [Scheduler] {len(roadmap_list)}개 로드맵 처리 시작...")
        
        for roadmap in roadmap_list:
            try:
                roadmap_id = str(roadmap.get("_id"))
                items = roadmap.get("items", [])
                if not items:
                    continue
                
                # 시작일 기준 오늘 일차 계산
                start_date = items[0].get("created_at")
                if not start_date:
                    continue
                
                today = datetime.utcnow()
                days_diff = (today - start_date).days + 1
                
                # 범위 내인 경우만 처리
                if 1 <= days_diff <= len(items):
                    goal = roadmap.get("name", "학습")
                    await generate_day_details(roadmap_id, days_diff, goal)
                    print(f"✅ [Scheduler] {roadmap.get('name')} - Day {days_diff} 상세 생성 완료")
                    
            except Exception as e:
                print(f"⚠️ [Scheduler] 로드맵 처리 오류: {e}")
                continue
        
        print(f"🎉 [Scheduler] 모든 로드맵 상세 생성 완료")
        
    except Exception as e:
        print(f"❌ [Scheduler] 전체 상세 생성 오류: {e}")


# 대화 히스토리는 MongoDB에서 직접 조회 (conversation_messages 컬렉션)
# 메모리 기반 conversation_history는 제거됨

# WebSocket 연결 관리 (세션 ID -> WebSocket 매핑)
active_connections: Dict[str, WebSocket] = {}

# Bedrock 클라이언트 초기화
# AWS Bedrock 설정
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

# Bedrock 클라이언트 초기화
bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name=AWS_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
)

# 모델 ID 상수
DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"  # 기본 채팅 (속도/비용 최적화)
ROADMAP_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"  # 로드맵 생성/질문 (고성능, Claude 3.5 Sonnet)

# LangChain 임베딩 모델 초기화 (한국어 특화 모델)
# jhgan/ko-sroberta-multitask: 한국어 RAG에 최적화된 모델 (768 차원)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "jhgan/ko-sroberta-multitask")
EMBEDDING_DIMENSION = 768  # ko-sroberta-multitask의 차원

# LangChain HuggingFace 임베딩 초기화
try:
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL_NAME,
        model_kwargs={'device': 'cpu'},  # GPU가 있으면 'cuda'로 변경 가능
        encode_kwargs={'normalize_embeddings': True}  # 정규화하여 코사인 유사도 최적화
    )
    print(f"✅ LangChain 임베딩 모델 로드 완료: {EMBEDDING_MODEL_NAME}")
except Exception as e:
    print(f"⚠️ 임베딩 모델 로드 실패: {e}")
    embeddings = None

# LangChain MongoDB Vector Store 초기화
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = int(os.getenv("MONGO_PORT", "27017"))
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "jiwon")
MONGO_USER = os.getenv("MONGO_USER", "")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "")
VECTOR_INDEX_NAME = os.getenv("MONGO_VECTOR_INDEX_NAME", "vector_index")

# MongoDB 연결 문자열
if MONGO_USER and MONGO_PASSWORD:
    MONGO_URI = f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB_NAME}?authSource=admin"
else:
    MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}/{MONGO_DB_NAME}"

# LangChain Vector Store 초기화 (conversation_messages 컬렉션 사용)
vector_store = None
try:
    if embeddings:
        mongo_client = MongoClient(MONGO_URI)
        collection = mongo_client[MONGO_DB_NAME]["conversation_messages"]
        
        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=VECTOR_INDEX_NAME,
            text_key="content",
            embedding_key="embedding"
        )
        print(f"✅ LangChain MongoDB Vector Store 초기화 완료: conversation_messages 컬렉션")
except Exception as e:
    print(f"⚠️ LangChain Vector Store 초기화 실패: {e}")
    vector_store = None



# 로드맵 프롬프트 (로드맵 생성 시에만 사용)
ROADMAP_SYSTEM_PROMPT = """# Role
PC/랩탑 학습 로드맵 생성을 위한 인터뷰어.

# Rules & Constraints
1. **단답 및 직구**: 한 번에 오직 '하나'의 질문만 출력. 인사, 서론, 요약 절대 금지.
2. **지능적 추출**: 사용자의 답변에서 [A]~[D] 정보를 최대한 찾아내어 기록하고, 누락된 항목만 질문.
3. **핀포인트 수정**: 사용자가 특정 정보를 수정하면 해당 항목만 즉시 업데이트. (전체 다시 묻지 말 것)
4. **일차별 과업 리스트화**: 
   - 각 `day` 객체 안에 해당 일차에 수행할 모든 과업을 `tasks` 배열로 넣을 것.
   - 과업은 최대한 잘게 쪼개어(Atomic) 나열하며, 배열 내에서 실행 순서대로 `rank`를 부여함.
5. **[필수] 기간 정확히 준수**: 
   - 사용자가 설정한 [C] 총 기간을 **반드시** 일 수로 변환하여 그 만큼의 day를 생성할 것.
   - 예: "3달" = 90일 → day 1부터 day 90까지 생성
   - 예: "2주" = 14일 → day 1부터 day 14까지 생성
   - **절대로 기간을 임의로 축소하지 말 것!**

# Status Check-List
[A] 총목표
[B] 세부 목표
[C] 총 기간 (예: 1주, 2주, 1달, 3달 등 → 일 수로 변환 필수)
[D] 일일 학습 시간

# Process Workflow
1. **[수집]**: 빈 항목([A]~[D]) 중 하나를 질문. 
2. **[교정]**: 수정 요청 시 해당 사안만 반영하여 다시 질문.
3. **[확인]**: 모든 정보 수집 시 요약 후 "이대로 일차별 과업이 묶인 로드맵을 생성할까요?" 질문.
4. **[출력]**: 승인 시 JSON 데이터만 출력하고 종료. **반드시 [C]에 해당하는 모든 일차를 포함할 것.**

# Output Format (JSON Only)
{
  "name": "로드맵 전체 이름 (사용자가 설정한 [A] 총목표를 기반으로 생성)",
  "total_days": number,  // 총 일수 (예: 3달 = 90일)
  "roadmap": [
    {
      "day": 1,
      "tasks": [
        { "rank": 1, "content": "과업1", "time": "시간" },
        { "rank": 2, "content": "과업2", "time": "시간" }
      ]
    },
    // ... day 2, 3, 4 ... 끝까지 모든 일차 생성
    {
      "day": 90,  // 3달이면 반드시 90일차까지
      "tasks": [...]
    }
  ]
}

# Important Notes
- **기간을 절대 축소하지 말 것**: 3달 = 90일이면 day 1 ~ day 90까지 모두 생성
- 비슷한 과업은 반복해도 됨 (복습, 심화 학습 등)
- 중간에 휴식일(Rest Day)을 넣어도 됨

# Start
사용자의 첫 메시지에서 정보를 분석하여 [A]~[D] 중 비어있는 항목에 대해 질문하며 시작하세요. 정보가 없다면 [A] 총목표부터 질문합니다."""

# 배치 생성용 프롬프트 (30일씩 나눠서 생성할 때 사용)
ROADMAP_BATCH_PROMPT = """# Role
로드맵의 특정 기간(Day {start_day} ~ Day {end_day})을 생성합니다.

# Context
- 총 목표: {goal}
- 총 기간: {total_days}일
- 일일 학습 시간: {daily_time}
- 현재 생성 범위: Day {start_day} ~ Day {end_day}
- 이 기간의 주제/키워드: {week_keywords}

# Rules
1. Day {start_day}부터 Day {end_day}까지만 생성
2. 주어진 키워드({week_keywords})에 맞는 과업 생성
3. 오직 JSON만 출력 (설명 없음)

# Output Format (JSON Only)
{{
  "batch": [
    {{
      "day": {start_day},
      "tasks": [
        {{ "rank": 1, "content": "과업1", "time": "시간" }},
        {{ "rank": 2, "content": "과업2", "time": "시간" }}
      ]
    }}
  ]
}}

# Start
Day {start_day}부터 Day {end_day}까지의 로드맵을 JSON으로 출력하세요."""

# 주차별 키워드 생성 프롬프트 (병렬 처리를 위해 먼저 계획 수립)
ROADMAP_PLAN_PROMPT = """# Role
학습 로드맵의 주차별 계획을 생성합니다.

# Context
- 총 목표: {goal}
- 세부 목표: {sub_goals}
- 총 기간: {total_days}일 ({total_weeks}주)
- 일일 학습 시간: {daily_time}

# Rules
1. 총 {total_weeks}주에 대한 주차별 키워드/주제를 생성
2. 각 주차는 7일에 해당
3. 오직 JSON만 출력

# Output Format (JSON Only)
{{
  "plan": [
    {{ "week": 1, "theme": "기초 개념 학습", "keywords": ["문법", "자료형", "변수"] }},
    {{ "week": 2, "theme": "심화 학습", "keywords": ["함수", "클래스", "모듈"] }}
  ]
}}

# Start
{total_weeks}주 분량의 주차별 계획을 JSON으로 출력하세요."""

# 과업 상세 내용 생성 프롬프트
TASK_DETAIL_PROMPT = """# Role
로드맵 과업의 상세 학습 내용을 생성합니다.

# Context
- 로드맵 목표: {goal}
- 일차: Day {day}
- 과업 제목: {task_content}
- 예상 시간: {task_time}

# Rules
1. 과업을 **구체적인 학습 단계**로 분해
2. 학습 목표, 핵심 개념, 실습 항목 포함
3. 초보자도 따라할 수 있도록 구체적으로 작성
4. 오직 JSON만 출력

# Output Format (JSON Only)
{{
  "details": {{
    "objectives": ["학습 목표 1", "학습 목표 2"],
    "key_concepts": ["핵심 개념 1", "핵심 개념 2", "핵심 개념 3"],
    "steps": [
      {{ "order": 1, "title": "단계 제목", "description": "상세 설명", "duration": "20분" }},
      {{ "order": 2, "title": "단계 제목", "description": "상세 설명", "duration": "30분" }}
    ],
    "resources": ["추천 자료/링크 1", "추천 자료/링크 2"],
    "tips": "유용한 팁이나 주의사항"
  }}
}}

# Start
'{task_content}' 과업의 상세 학습 내용을 JSON으로 출력하세요."""


def get_user_id_from_token(authorization: Optional[str] = Header(None)) -> Optional[str]:
    """JWT 토큰에서 user_id 추출"""
    print(f"🔍 [JWT Debug] Authorization 헤더 확인: {authorization[:50] if authorization else None}...")
    
    if not authorization:
        print("⚠️ [JWT Debug] Authorization 헤더가 없습니다.")
        return None
    
    try:
        # "Bearer <token>" 형식에서 토큰 추출
        if not authorization.startswith("Bearer "):
            print("⚠️ [JWT Debug] Bearer 토큰 형식이 아닙니다.")
            return None
        
        token = authorization.replace("Bearer ", "").strip()
        print(f"✅ [JWT Debug] 토큰 추출 완료 (길이: {len(token)})")
        
        # JWT secret key (환경 변수에서 가져오거나 기본값 사용)
        jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
        print(f"🔑 [JWT Debug] JWT_SECRET 환경 변수: {'설정됨' if jwt_secret != 'your-secret-key-change-in-production' else '기본값 사용'}")
        
        # JWT 토큰 디코딩 (검증 없이 payload만 읽기)
        # 주의: 실제 운영 환경에서는 검증이 필요하지만, 
        # 여기서는 단순히 payload를 읽기만 함
        try:
            decoded = jwt.decode(token, jwt_secret, algorithms=["HS256"], options={"verify_signature": False})
            print(f"✅ [JWT Debug] JWT 디코딩 성공 (검증 없이)")
        except jwt.DecodeError as e:
            print(f"⚠️ [JWT Debug] JWT 디코딩 실패, payload만 읽기 시도: {e}")
            # 검증 실패 시 payload만 읽기
            import base64
            parts = token.split('.')
            if len(parts) != 3:
                print(f"❌ [JWT Debug] 토큰 형식 오류: {len(parts)}개 부분 (예상: 3개)")
                return None
            payload = parts[1]
            # base64 padding 추가
            payload += '=' * (4 - len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload))
            print(f"✅ [JWT Debug] Payload 직접 디코딩 성공")
        
        print(f"📋 [JWT Debug] 디코딩된 payload: {json.dumps(decoded, indent=2, ensure_ascii=False)}")
        
        # user_id 또는 sub (username) 추출
        # JWT payload에서 user_id가 있으면 사용, 없으면 sub(username) 사용
        user_id_from_payload = decoded.get("user_id")
        sub_username = decoded.get("sub")
        
        print(f"🔍 [JWT Debug] payload에서 추출 - user_id: {user_id_from_payload}, sub: {sub_username}")
        
        # user_id가 UUID 형식인지 확인
        if user_id_from_payload:
            try:
                # UUID 형식인지 확인
                uuid.UUID(user_id_from_payload)
                print(f"✅ [JWT Debug] user_id가 UUID 형식입니다: {user_id_from_payload}")
                return user_id_from_payload
            except (ValueError, TypeError):
                print(f"⚠️ [JWT Debug] user_id가 UUID 형식이 아닙니다: {user_id_from_payload}")
        
        # user_id가 없거나 UUID 형식이 아니면 sub(username) 반환
        # 주의: username은 UUID가 아니므로, 실제 user_id를 조회해야 할 수 있음
        if sub_username:
            print(f"⚠️ [JWT Debug] user_id가 없어서 sub(username)를 반환합니다: {sub_username}")
            print(f"⚠️ [JWT Debug] 주의: username은 UUID가 아니므로, 실제 user_id 조회가 필요할 수 있습니다.")
            return sub_username
        else:
            print(f"❌ [JWT Debug] user_id와 sub 모두 없습니다. payload 키: {list(decoded.keys())}")
            return None
    except Exception as e:
        print(f"❌ [JWT Debug] JWT 토큰 파싱 실패: {e}")
        import traceback
        traceback.print_exc()
        return None


async def get_session_config(session_id: str) -> Optional[Dict]:
    """세션 설정 가져오기"""
    try:
        session_configs = await get_collection("session_configs")
        config = await session_configs.find_one({"session_id": session_id})
        return config
    except Exception as e:
        print(f"⚠️ 세션 설정 조회 실패: {e}")
        return None


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
    """대화 메시지를 개별 문서로 저장 (embedding 포함)
    
    개선된 구조:
    conversation_messages 컬렉션:
    {
        _id: ObjectId,
        session_id: "abc",
        user_id: "user-uuid",
        role: "user",
        content: "안녕",
        embedding: [0.1, 0.2, ...],  # Vector Store용
        created_at: ...
    }
    """
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


def search_similar_messages(query: str, user_id: Optional[str] = None, limit: int = 5) -> List[Dict]:
    """LangChain Vector Store에서 유사한 메시지 검색"""
    try:
        if vector_store is None:
            print("⚠️ Vector Store가 초기화되지 않았습니다.")
            return []
        
        # 필터 조건 생성 (user_id가 있을 때만)
        filter_dict = None
        if user_id:
            filter_dict = {"user_id": user_id}
        
        # 유사도 검색 (with_score=True로 점수도 반환)
        results = vector_store.similarity_search_with_score(
            query=query,
            k=limit,
            pre_filter=filter_dict
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
        print(f"⚠️ Vector 검색 실패: {e}")
        return []


async def get_rag_context(query: str, session_id: str, user_id: Optional[str] = None, limit: int = 5) -> str:
    """RAG를 위한 관련 대화 컨텍스트 가져오기 (LangChain Vector Search 사용)"""
    try:
        # LangChain Vector Store로 유사 메시지 검색
        similar_messages = search_similar_messages(
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




# 로드맵 QA 프롬프트 (로드맵 질문 모드)
ROADMAP_QA_SYSTEM_PROMPT = """당신은 사용자의 학습을 돕는 친절하고 전문적인 'AI 멘토'입니다.
현재 사용자는 자신이 생성한 학습 로드맵을 따라 공부하고 있습니다.
사용자가 로드맵의 특정 과업이나 개념에 대해 질문하면, 제공된 로드맵 컨텍스트를 바탕으로 구체적이고 실질적인 도움을 주세요.

[가이드라인]
1. 답변은 친절하고 격려하는 어조('~해요', '~습니다')를 사용하세요.
2. 특정 페르소나(캐릭터)를 연기하지 마세요. 오직 전문적인 멘토로서 답변하세요.
3. 개념 설명은 쉽고 명확하게, 필요한 경우 코드 예시를 포함하세요.
4. 사용자가 과업을 완료할 수 있도록 구체적인 팁을 제공하세요.
5. 질문이 로드맵과 관련 없다면 부드럽게 로드맵과 연관지어 답변하거나 일반적인 지식을 제공하세요."""

async def get_system_prompt(session_id: str, rag_context: str = "") -> str:
    """세션에 맞는 시스템 프롬프트 가져오기"""
    config = await get_session_config(session_id)
    
    # 로드맵 모드인 경우
    if config and config.get("mode") == "roadmap":
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


def parse_roadmap_json(text: str) -> Optional[Dict]:
    """응답 텍스트에서 로드맵 JSON을 파싱"""
    try:
        import re
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
    model_id: str = DEFAULT_MODEL_ID
) -> List[Dict]:
    """7일 단위로 로드맵 배치 생성 (키워드 기반)
    
    Args:
        start_day: 시작 일차
        end_day: 종료 일차
        context: 로드맵 컨텍스트 (goal, total_days, daily_time, week_keywords)
        model_id: 사용할 AI 모델 ID
    
    Returns:
        생성된 day 객체들의 리스트
    """
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
        
        # Bedrock API 호출 (기존 bedrock_runtime 사용)
        bedrock = bedrock_runtime
        
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
            lambda: bedrock.invoke_model(
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
        import re
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
    model_id: str = DEFAULT_MODEL_ID
) -> List[Dict]:
    """주차별 키워드 계획 생성
    
    Returns:
        [{"week": 1, "theme": "기초", "keywords": ["문법", "변수"]}, ...]
    """
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
        
        # Bedrock API 호출 (기존 bedrock_runtime 사용)
        bedrock = bedrock_runtime
        
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
            lambda: bedrock.invoke_model(
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
        
        import re
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
    model_id: str = DEFAULT_MODEL_ID
) -> Optional[Dict]:
    """단일 과업의 상세 내용 생성
    
    Returns:
        {
            "objectives": [...],
            "key_concepts": [...],
            "steps": [{"order": 1, "title": "", "description": "", "duration": ""}],
            "resources": [...],
            "tips": ""
        }
    """
    try:
        print(f"📝 [TaskDetail] Day {day} - '{task_content}' 상세 생성 중...")
        
        prompt = TASK_DETAIL_PROMPT.format(
            goal=goal,
            day=day,
            task_content=task_content,
            task_time=task_time
        )
        
        bedrock = bedrock_runtime
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
            lambda: bedrock.invoke_model(modelId=model_id, body=body)
        )
        
        response_body = json.loads(response["body"].read())
        content = response_body.get("content", [])
        if content and len(content) > 0:
            response_text = content[0].get("text", "")
        else:
            return None
        
        import re
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
    """특정 일차의 모든 과업에 대해 상세 내용 생성 후 DB 업데이트
    
    Args:
        roadmap_id: 로드맵 MongoDB ID
        day: 일차 (1부터 시작)
        goal: 로드맵 목표
    
    Returns:
        성공 여부
    """
    try:
        from bson import ObjectId
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
    """전체 로드맵을 병렬로 생성 (주차별 키워드 기반)
    
    1단계: 주차별 키워드 생성
    2단계: 모든 주차를 병렬로 생성 (asyncio.gather)
    """
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
            print(f"⚠️ [FullRoadmap] 누락된 일차 발견: {len(missing_days)}일 (Day {min(missing_days)} ~ Day {max(missing_days)})")
            # 누락된 일차를 주차별로 그룹화하여 재생성 시도
            retry_tasks = []
            for start_day in range(min(missing_days), max(missing_days) + 1, 7):
                end_day = min(start_day + 6, max(missing_days))
                week_num = (start_day - 1) // 7 + 1
                
                # 해당 주차의 키워드 찾기
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
                
                # 재생성 시도 (병렬)
                retry_tasks.append((start_day, end_day, context, week_keywords, theme))
            
            # 재생성 병렬 실행
            if retry_tasks:
                retry_results = await asyncio.gather(*[
                    generate_roadmap_batch(start_day, end_day, context, ROADMAP_MODEL_ID)
                    for start_day, end_day, context, _, _ in retry_tasks
                ], return_exceptions=True)
                
                # 결과 처리
                for idx, (start_day, end_day, context, week_keywords, theme) in enumerate(retry_tasks):
                    result = retry_results[idx]
                    if isinstance(result, list) and result:
                        all_items.extend(result)
                        print(f"✅ [FullRoadmap] 재생성 성공: Day {start_day} ~ Day {end_day}")
                    else:
                        # 재생성 실패 시 주제 기반 기본값 생성 (더 구체적으로)
                        print(f"⚠️ [FullRoadmap] 재생성 실패, 기본값 생성: Day {start_day} ~ Day {end_day}")
                        for day in range(start_day, end_day + 1):
                            if day not in {item.get("day") for item in all_items}:
                                # 주차별 주제에 맞는 구체적인 과업 생성
                                day_in_week = ((day - 1) % 7) + 1
                                if day_in_week <= 3:
                                    task1 = f"{theme} - 이론 및 개념 학습" if theme else f"{goal} - 기초 이론 학습"
                                    task2 = f"{theme} - 예제 코드 분석" if theme else f"{goal} - 예제 실습"
                                elif day_in_week <= 5:
                                    task1 = f"{theme} - 실습 프로젝트 진행" if theme else f"{goal} - 실습 프로젝트"
                                    task2 = f"{theme} - 코드 작성 및 테스트" if theme else f"{goal} - 코드 작성"
                                else:
                                    task1 = f"{theme} - 복습 및 정리" if theme else f"{goal} - 복습"
                                    task2 = f"{theme} - 추가 학습 및 보완" if theme else f"{goal} - 심화 학습"
                                
                                all_items.append({
                                    "day": day,
                                    "tasks": [
                                        {"rank": 1, "content": task1, "time": "3시간"},
                                        {"rank": 2, "content": task2, "time": "3시간"}
                                    ]
                                })
        
        # day 순서대로 정렬
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
    """로드맵 데이터를 RAG용 텍스트로 변환 (새 tasks 구조 지원)"""
    roadmap_name = roadmap_data.get("name", "로드맵")
    roadmap_items = roadmap_data.get("roadmap", [])
    
    text_parts = [f"로드맵: {roadmap_name}"]
    
    for item in roadmap_items:
        day = item.get("day", "")
        tasks = item.get("tasks", [])
        
        if tasks:
            # 새 구조 (tasks 배열)
            task_texts = []
            for task in tasks:
                content = task.get("content", "")
                time = task.get("time", "")
                task_texts.append(f"  - {content} ({time})")
            text_parts.append(f"일차 {day}:")
            text_parts.extend(task_texts)
        else:
            # 레거시 구조
            content = item.get("content", "")
            time = item.get("time", "")
            text_parts.append(f"일차 {day}: {content} (학습 시간: {time})")
    
    return "\n".join(text_parts)


async def save_roadmap(roadmap_data: Dict, session_id: str, user_id: Optional[str] = None) -> Optional[Dict]:
    """로드맵 데이터를 MongoDB에 저장 (새 tasks 배열 구조 지원)
    
    새로운 구조:
    {
        "name": "로드맵 이름",
        "user_id": "...",
        "session_id": "...",
        "items": [
            {
                "day": 1,
                "tasks": [
                    { "rank": 1, "content": "과업1", "time": "15분", "is_completed": 0 },
                    { "rank": 2, "content": "과업2", "time": "30분", "is_completed": 0 }
                ],
                "created_at": ...
            }
        ]
    }
    """
    try:
        print(f"💾 [save_roadmap] 함수 호출됨 - session_id: {session_id}, user_id: {user_id}")
        print(f"💾 [save_roadmap] roadmap_data 키: {list(roadmap_data.keys())}")
        print(f"💾 [save_roadmap] roadmap_data['name']: {roadmap_data.get('name')}")
        
        roadmap_items = roadmap_data.get("roadmap", [])
        print(f"💾 [save_roadmap] roadmap 배열 길이: {len(roadmap_items)}")
        
        if not roadmap_items:
            print(f"❌ [save_roadmap] roadmap 배열이 비어있음!")
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
            
            # 새 구조: tasks 배열 처리
            tasks_data = item_data.get("tasks", [])
            if tasks_data:
                # 새 구조 (tasks 배열)
                tasks = []
                for task in tasks_data:
                    tasks.append({
                        "rank": task.get("rank", 0),
                        "content": task.get("content", ""),
                        "time": task.get("time", ""),
                        "is_completed": 0,
                        "completed_at": None
                    })
                
                items.append({
                    "day": item_data.get("day"),
                    "tasks": tasks,
                    "created_at": item_created_at
                })
            else:
                # 레거시 구조 (content 단일 필드) -> 변환
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
        
        # 로드맵 문서 생성
        roadmap_doc = {
            "name": roadmap_data.get("name", "로드맵"),
            "user_id": user_id,
            "session_id": session_id,
            "items": items,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # MongoDB에 저장
        print(f"💾 [save_roadmap] MongoDB에 저장 시작...")
        print(f"💾 [save_roadmap] roadmap_doc 키: {list(roadmap_doc.keys())}")
        print(f"💾 [save_roadmap] roadmap_doc['name']: {roadmap_doc['name']}")
        print(f"💾 [save_roadmap] roadmap_doc['items'] 길이: {len(roadmap_doc['items'])}")
        
        roadmaps = await get_collection("roadmaps")
        result = await roadmaps.insert_one(roadmap_doc)
        
        if result.inserted_id:
            roadmap_doc["_id"] = result.inserted_id
            print(f"✅ [save_roadmap] 로드맵 저장 완료 - _id: {result.inserted_id}, name: {roadmap_doc['name']}")
        else:
            print(f"❌ [save_roadmap] insert_one이 inserted_id를 반환하지 않음!")
            return None
        
        # 로드맵 내용을 RAG로 저장
        try:
            roadmap_text = format_roadmap_for_rag(roadmap_data)
            await save_conversation_message(
                session_id=session_id,
                role="roadmap",
                content=roadmap_text,
                user_id=user_id
            )
            print(f"✅ 로드맵 RAG 저장 완료: {roadmap_doc['name']}")
        except Exception as e:
            print(f"⚠️ 로드맵 RAG 저장 실패 (로드맵 자체는 저장됨): {e}")
        
        return roadmap_doc
    except Exception as e:
        print(f"⚠️ 로드맵 저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return None


# Pydantic 모델들
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None  # UUID 문자열
    model_id: Optional[str] = DEFAULT_MODEL_ID
    max_tokens: Optional[int] = 100000
    temperature: Optional[float] = 0.7
    conversation_history: Optional[List[Dict]] = None


class ChatResponse(BaseModel):
    response: str
    model_id: str
    session_id: str


class PersonalityResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


class SelectPersonalityRequest(BaseModel):
    session_id: str
    personality_id: int
    user_id: Optional[str] = None  # UUID 문자열


class StartRoadmapRequest(BaseModel):
    session_id: str
    user_id: Optional[str] = None  # UUID 문자열


class SearchRequest(BaseModel):
    query: str
    user_id: Optional[str] = None  # UUID 문자열
    limit: Optional[int] = 5


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


# API 엔드포인트들
@app.get("/")
def read_root():
    return {"service": "ai-chat-service", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/debug/personalities")
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


class UpdateSessionModeRequest(BaseModel):
    mode: str  # 'chat' or 'roadmap'

@app.put("/sessions/{session_id}/mode")
async def update_session_mode(session_id: str, request: UpdateSessionModeRequest):
    """세션 모드 업데이트 (chat <-> roadmap)"""
    try:
        session_configs = await get_collection("session_configs")
        
        # 세션 존재 확인
        config = await session_configs.find_one({"session_id": session_id})
        if not config:
            # 세션이 없으면 생성 (user_id는 알 수 없으므로 None 처리하거나 에러)
            # 여기서는 편의상 생성하지 않고 에러 리턴 (WebSocket 접속 시 생성됨)
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

@app.get("/sessions/user/{user_id}")
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





@app.get("/personalities", response_model=List[PersonalityResponse])
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


@app.post("/personalities/select")
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


@app.post("/chat/roadmap/start")
async def start_roadmap(request: StartRoadmapRequest):
    """로드맵 생성 모드 시작"""
    try:
        # 세션 설정 가져오기 또는 생성
        session_configs = await get_collection("session_configs")
        config = await session_configs.find_one({"session_id": request.session_id})
        
        update_data = {
            "mode": "roadmap",
            "updated_at": datetime.utcnow()
        }
        
        if request.user_id:
            update_data["user_id"] = request.user_id
        
        if not config:
            # 새 세션 설정 생성
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
            # 기존 세션 설정 업데이트
            await session_configs.update_one(
                {"session_id": request.session_id},
                {"$set": update_data}
            )
        
        # 로드맵 모드 시작 시 대화 히스토리는 MongoDB에서 관리되므로 별도 초기화 불필요
        
        return {
            "message": "로드맵 생성 모드가 시작되었습니다.",
            "session_id": request.session_id,
            "mode": "roadmap"
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"로드맵 모드 시작 중 오류 발생: {str(e)}")


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, 
    user_id_from_token: Optional[str] = Depends(get_user_id_from_token)
):
    """Bedrock을 사용한 채팅 엔드포인트"""
    try:
        # 세션 ID 처리
        session_id = request.session_id
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # user_id 우선순위: JWT 토큰 > request.user_id
        user_id = user_id_from_token or request.user_id
        print(f"🔍 [Chat Debug] 최종 user_id: {user_id} (JWT: {user_id_from_token}, Request: {request.user_id})")
        
        # user_id가 있으면 세션 설정에 저장
        config = await get_session_config(session_id)
        if user_id:
            try:
                session_configs = await get_collection("session_configs")
                if not config:
                    # 새 세션 설정 생성
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
                    # user_id 업데이트
                    await session_configs.update_one(
                        {"session_id": session_id},
                        {"$set": {"user_id": user_id, "updated_at": datetime.utcnow()}}
                    )
                    config["user_id"] = user_id
            except ValueError:
                # 잘못된 UUID 형식은 무시
                pass
        
        # config 다시 가져오기 (위에서 생성했을 수 있음)
        if not config:
            config = await get_session_config(session_id)
        
        # 로드맵 모드 확인 및 모델 ID 결정
        if config and config.get("mode") == "roadmap":
            # 로드맵 모드일 때는 ROADMAP_MODEL_ID 사용
            model_id = ROADMAP_MODEL_ID
            print(f"📋 [Chat] 로드맵 모드 - 모델 ID: {model_id}")
            rag_context = ""  # 로드맵 모드에서는 RAG 사용 안 함
        elif request.message.startswith("[오늘 로드맵 질문]"):
            # 로드맵 질문 모드
            model_id = ROADMAP_MODEL_ID
            rag_context = "" # 컨텍스트가 메시지에 포함되어 있음
            print(f"📚 [Chat] 로드맵 질문 감지됨 - 모델 ID: {model_id}")
        else:
            # 일반 채팅 모드일 때는 요청된 모델 ID 또는 기본값(하이쿠) 사용
            model_id = request.model_id or DEFAULT_MODEL_ID
            print(f"💬 [Chat] 일반 채팅 모드 - 모델 ID: {model_id}")
            # RAG 컨텍스트 생성 (일반 채팅 모드에서만)
            # RAG 실패 시에도 채팅은 계속 진행되도록 try-except 처리
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
        
        # 시스템 프롬프트 가져오기 (RAG 컨텍스트 포함)
        if request.message.startswith("[오늘 로드맵 질문]"):
            system_prompt = ROADMAP_QA_SYSTEM_PROMPT
        else:
            system_prompt = await get_system_prompt(session_id, rag_context=rag_context)
        
        # 대화 히스토리 가져오기 (MongoDB에서 조회)
        messages = []
        if request.conversation_history:
            # 클라이언트에서 제공한 히스토리 사용
            for msg in request.conversation_history:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
        else:
            # MongoDB에서 세션의 최근 메시지 조회
            stored_messages = await get_conversation_messages(session_id, limit=50)
            for msg in stored_messages:
                if isinstance(msg, dict) and "role" in msg and "content" in msg:
                    messages.append({
                        "role": msg["role"],
                        "content": msg["content"]
                    })
        
        # 현재 사용자 메시지 추가
        messages.append({
            "role": "user",
            "content": request.message,
        })
        
        # user_id 우선순위: 세션 설정의 user_id > JWT 토큰 > request.user_id
        user_id_for_save = None
        if config and config.get("user_id"):
            user_id_for_save = str(config["user_id"])
            print(f"💾 [Chat Debug] user_id_for_save (세션 설정): {user_id_for_save}")
        elif user_id:
            user_id_for_save = user_id
            print(f"💾 [Chat Debug] user_id_for_save (JWT/Request): {user_id_for_save}")
        elif request.user_id:
            user_id_for_save = request.user_id
            print(f"💾 [Chat Debug] user_id_for_save (Request): {user_id_for_save}")
        else:
            print(f"⚠️ [Chat Debug] user_id_for_save가 None입니다. RAG 저장 시 user_id가 저장되지 않습니다.")
        
        # 사용자 메시지를 백그라운드에서 저장 (non-blocking)
        asyncio.create_task(save_conversation_message(
            session_id=session_id,
            role="user",
            content=request.message,
            user_id=user_id_for_save
        ))
        
        # Bedrock 요청 페이로드 구성
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                "system": system_prompt,
                "messages": messages,
            }
        )

        # Bedrock API 호출
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

        # 응답 파싱
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
        
        # 로드맵 모드이고 JSON 로드맵이 포함되어 있으면 저장 (config는 이미 위에서 가져옴)
        roadmap_saved = False
        if config and config.get("mode") == "roadmap":
            print(f"🔍 [Roadmap] 로드맵 모드 감지됨. 응답에서 JSON 검색 중...")
            print(f"🔍 [Roadmap] 응답 길이: {len(assistant_message)} 문자")
            print(f"🔍 [Roadmap] 응답 일부: {assistant_message[:200]}...")
            
            import re
            json_str = None
            
            # 패턴 1: ```json ... ``` (가장 우선)
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', assistant_message)
            if json_match:
                json_str = json_match.group(1)
                print(f"✅ [Roadmap] JSON 블록 발견 (```json 형식)")
            else:
                # 패턴 2: ``` ... ``` (json 없이)
                json_match = re.search(r'```\s*([\s\S]*?)\s*```', assistant_message)
                if json_match:
                    json_str = json_match.group(1)
                    print(f"✅ [Roadmap] JSON 블록 발견 (``` 형식)")
                else:
                    # 패턴 3: { ... } 전체 JSON 객체 찾기 (중괄호 매칭)
                    # "roadmap" 키워드가 있는 첫 번째 { 부터 시작해서 중괄호가 모두 닫힐 때까지 추출
                    roadmap_start = assistant_message.find('"roadmap"')
                    if roadmap_start != -1:
                        # "roadmap" 앞에서 { 찾기
                        brace_start = assistant_message.rfind('{', 0, roadmap_start)
                        if brace_start != -1:
                            # 중괄호 매칭으로 전체 JSON 추출
                            brace_count = 0
                            brace_end = brace_start
                            for i in range(brace_start, len(assistant_message)):
                                if assistant_message[i] == '{':
                                    brace_count += 1
                                elif assistant_message[i] == '}':
                                    brace_count -= 1
                                    if brace_count == 0:
                                        brace_end = i + 1
                                        break
                            
                            if brace_count == 0:
                                json_str = assistant_message[brace_start:brace_end]
                                print(f"✅ [Roadmap] JSON 객체 발견 (중괄호 매칭)")
            
            if json_str:
                try:
                    # JSON 문자열 정리 (앞뒤 공백 제거)
                    json_str = json_str.strip()
                    print(f"🔍 [Roadmap] JSON 문자열 길이: {len(json_str)}")
                    print(f"🔍 [Roadmap] JSON 문자열 시작: {json_str[:100]}...")
                    print(f"🔍 [Roadmap] JSON 문자열 끝: ...{json_str[-100:]}")
                    
                    # JSON 주석 제거 (// 주석 및 /* */ 주석)
                    import re
                    # // 주석 제거 (문자열 내부가 아닌 경우)
                    json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
                    # /* */ 주석 제거
                    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                    # 빈 줄 제거
                    json_str = re.sub(r'\n\s*\n', '\n', json_str)
                    # 앞뒤 공백 다시 제거
                    json_str = json_str.strip()
                    
                    print(f"🔍 [Roadmap] 주석 제거 후 JSON 문자열 길이: {len(json_str)}")
                    
                    # JSON 파싱
                    roadmap_data = json.loads(json_str)
                    print(f"✅ [Roadmap] JSON 파싱 성공")
                    print(f"🔍 [Roadmap] 파싱된 데이터 키: {list(roadmap_data.keys())}")
                    
                    # roadmap 필드 확인
                    if roadmap_data.get("roadmap") and isinstance(roadmap_data.get("roadmap"), list):
                        print(f"✅ [Roadmap] roadmap 배열 확인됨 (길이: {len(roadmap_data.get('roadmap', []))})")
                        
                        # user_id 우선순위: 세션 설정의 user_id > JWT 토큰 > request.user_id
                        if not user_id_for_save:
                            if config and config.get("user_id"):
                                user_id_for_save = str(config["user_id"])
                            elif user_id:
                                user_id_for_save = user_id
                            elif request.user_id:
                                user_id_for_save = request.user_id
                        
                        print(f"💾 [Roadmap] 로드맵 저장 시작 - session_id: {session_id}, user_id: {user_id_for_save}")
                        
                        # total_days가 있고, 현재 생성된 일차보다 크면 배치 생성 수행
                        total_days = roadmap_data.get("total_days", 0)
                        current_items = len(roadmap_data.get("roadmap", []))
                        
                        if total_days > current_items and total_days > 30:
                            print(f"🔄 [Roadmap] 배치 생성 필요: total_days={total_days}, current_items={current_items}")
                            # 백그라운드에서 나머지 일차 생성
                            full_roadmap = await generate_full_roadmap(
                                roadmap_info=roadmap_data,
                                session_id=session_id,
                                user_id=user_id_for_save
                            )
                            if full_roadmap:
                                roadmap_data = full_roadmap
                                print(f"✅ [Roadmap] 배치 생성 완료: {len(roadmap_data.get('roadmap', []))}일")
                        
                        result = await save_roadmap(roadmap_data, session_id, user_id_for_save)
                        
                        if result:
                            print(f"✅ [Roadmap] 로드맵 저장 완료: {roadmap_data.get('name', '로드맵')}, _id: {result.get('_id')}, user_id: {user_id_for_save}")
                            roadmap_saved = True
                            
                            # Day 1 상세 자동 생성 (백그라운드)
                            roadmap_id = str(result.get('_id'))
                            goal = roadmap_data.get('name', '학습')
                            asyncio.create_task(generate_day_details(roadmap_id, 1, goal))
                            print(f"📝 [Roadmap] Day 1 상세 생성 요청됨 (백그라운드)")
                            
                            # JSON 부분을 제거하고 간단한 메시지로 대체
                            roadmap_name = roadmap_data.get('name', '로드맵')
                            total_items = len(roadmap_data.get('roadmap', []))
                            assistant_message = f"✅ 로드맵 '{roadmap_name}'이 생성되었습니다! ({total_items}일) 로드맵 목록에서 확인하실 수 있습니다."
                        else:
                            print(f"❌ [Roadmap] 로드맵 저장 실패: save_roadmap이 None 반환")
                    else:
                        print(f"⚠️ [Roadmap] roadmap 필드가 없거나 배열이 아님")
                        print(f"🔍 [Roadmap] roadmap 필드 값: {roadmap_data.get('roadmap')}")
                except json.JSONDecodeError as e:
                    print(f"❌ [Roadmap] JSON 파싱 실패: {e}")
                    print(f"🔍 [Roadmap] 문제가 있는 JSON 문자열 (처음 500자): {json_str[:500]}")
                    print(f"🔍 [Roadmap] 문제가 있는 JSON 문자열 (마지막 500자): {json_str[-500:]}")
                    import traceback
                    traceback.print_exc()
                except Exception as e:
                    print(f"❌ [Roadmap] 로드맵 저장 중 오류: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"⚠️ [Roadmap] 응답에서 JSON을 찾을 수 없음")
                print(f"🔍 [Roadmap] 전체 응답: {assistant_message}")
        else:
            if not config:
                print(f"⚠️ [Roadmap] config가 None입니다")
            elif config.get("mode") != "roadmap":
                print(f"⚠️ [Roadmap] 모드가 'roadmap'이 아님: {config.get('mode')}")
        
        # AI 응답을 백그라운드에서 저장 (non-blocking)
        asyncio.create_task(save_conversation_message(
            session_id=session_id,
            role="assistant",
            content=assistant_message,
            user_id=user_id_for_save
        ))
        
        # AI 응답을 히스토리에 추가 (이미 MongoDB에 저장됨)
        messages.append({
            "role": "assistant",
            "content": assistant_message,
        })
        
        # 히스토리는 MongoDB에서 관리하므로 메모리 기반 저장 제거

        return ChatResponse(
            response=assistant_message,
            model_id=model_id,  # 이미 로드맵 모드에 따라 적절히 설정됨
            session_id=session_id,
        )

    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"❌ [Chat Error] 오류 발생: {str(e)}")
        print(f"❌ [Chat Error] Traceback:\n{error_traceback}")
        raise HTTPException(
            status_code=500, 
            detail=f"채팅 처리 중 오류 발생: {str(e)}"
        )


@app.post("/chat/clear")
async def clear_history(session_id: str):
    """특정 세션의 대화 히스토리 삭제 (MongoDB에서)"""
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


@app.post("/chat/search")
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


@app.get("/roadmaps", response_model=List[RoadmapResponse])
async def get_roadmaps(user_id: Optional[str] = None):
    """사용자별 로드맵 목록 조회"""
    try:
        roadmaps_collection = await get_collection("roadmaps")
        
        query_filter = {}
        if user_id:
            query_filter["user_id"] = user_id
        
        print(f"🔍 [get_roadmaps] user_id: {user_id}, query_filter: {query_filter}")
        cursor = roadmaps_collection.find(query_filter).sort("created_at", -1)
        roadmaps = await cursor.to_list(length=None)
        print(f"✅ [get_roadmaps] 조회된 로드맵 개수: {len(roadmaps)}")
        
        result = []
        for roadmap in roadmaps:
            items = roadmap.get("items", [])
            print(f"🔍 [get_roadmaps] 로드맵 '{roadmap.get('name')}' - items 개수: {len(items)}")
            formatted_items = []
            for idx, item in enumerate(items):
                # 새 구조: tasks 배열이 있는 경우
                tasks = item.get("tasks", [])
                if tasks:
                    # tasks 배열을 포함한 새 구조
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
                                "details": task.get("details")  # 상세 내용 추가
                            }
                            for task in tasks
                        ],
                        "created_at": item.get("created_at").isoformat() if item.get("created_at") else None
                    })
                    if idx == 0:
                        print(f"✅ [get_roadmaps] 첫 번째 항목 (day: {item.get('day')}) - tasks 개수: {len(tasks)}, created_at: {item.get('created_at')}")
                else:
                    # 레거시 구조: content, time 직접 필드
                    formatted_items.append({
                        "id": idx,
                        "day": item.get("day"),
                        "content": item.get("content", ""),
                        "time": item.get("time", ""),
                        "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                        "is_completed": bool(item.get("is_completed", 0)),
                        "completed_at": item.get("completed_at").isoformat() if item.get("completed_at") else None
                    })
                    if idx == 0:
                        print(f"✅ [get_roadmaps] 첫 번째 항목 (day: {item.get('day')}) - 레거시 구조, created_at: {item.get('created_at')}")
            
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


@app.get("/roadmaps/{roadmap_id}", response_model=RoadmapResponse)
async def get_roadmap(roadmap_id: str):
    """특정 로드맵 상세 조회"""
    try:
        from bson import ObjectId
        from bson.errors import InvalidId
        roadmaps_collection = await get_collection("roadmaps")
        
        # ObjectId로 변환 시도
        try:
            object_id = ObjectId(roadmap_id)
            roadmap = await roadmaps_collection.find_one({"_id": object_id})
        except (InvalidId, ValueError, TypeError) as e:
            # ObjectId 형식이 아닌 경우, 문자열로 직접 검색 시도
            print(f"⚠️ ObjectId 변환 실패, 문자열로 검색 시도: {roadmap_id}, 오류: {e}")
            roadmap = await roadmaps_collection.find_one({"_id": roadmap_id})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail=f"로드맵을 찾을 수 없습니다. (ID: {roadmap_id})")
        
        print(f"🔍 [get_roadmap] 로드맵 '{roadmap.get('name')}' 조회 성공")
        items = roadmap.get("items", [])
        print(f"🔍 [get_roadmap] items 개수: {len(items)}")
        formatted_items = []
        for idx, item in enumerate(items):
            # 새 구조: tasks 배열이 있는 경우
            tasks = item.get("tasks", [])
            if tasks:
                # tasks 배열을 포함한 새 구조
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
                            "details": task.get("details")  # 상세 내용 추가
                        }
                        for task in tasks
                    ],
                    "created_at": item.get("created_at").isoformat() if item.get("created_at") else None
                })
                if idx == 0:
                    print(f"✅ [get_roadmap] 첫 번째 항목 (day: {item.get('day')}) - tasks 개수: {len(tasks)}, created_at: {item.get('created_at')}")
            else:
                # 레거시 구조: content, time 직접 필드
                formatted_items.append({
                    "id": idx,
                    "day": item.get("day"),
                    "content": item.get("content", ""),
                    "time": item.get("time", ""),
                    "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                    "is_completed": bool(item.get("is_completed", 0)),
                    "completed_at": item.get("completed_at").isoformat() if item.get("completed_at") else None
                })
                if idx == 0:
                    print(f"✅ [get_roadmap] 첫 번째 항목 (day: {item.get('day')}) - 레거시 구조, created_at: {item.get('created_at')}")
        
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


@app.post("/roadmaps/{roadmap_id}/generate-details/{day}")
async def generate_roadmap_day_details(roadmap_id: str, day: int):
    """특정 일차의 과업 상세 내용 생성
    
    Args:
        roadmap_id: 로드맵 ID
        day: 일차 (1부터 시작)
    """
    try:
        from bson import ObjectId
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


@app.post("/roadmaps/{roadmap_id}/generate-today-details")
async def generate_today_details(roadmap_id: str):
    """오늘 날짜에 해당하는 과업 상세 내용 생성
    
    로드맵 시작일로부터 오늘이 몇 일차인지 계산하여 해당 일차의 상세 생성
    """
    try:
        from bson import ObjectId
        roadmaps = await get_collection("roadmaps")
        roadmap = await roadmaps.find_one({"_id": ObjectId(roadmap_id)})
        
        if not roadmap:
            raise HTTPException(status_code=404, detail="로드맵을 찾을 수 없습니다")
        
        # 시작일 계산 (첫 번째 item의 created_at)
        items = roadmap.get("items", [])
        if not items:
            raise HTTPException(status_code=400, detail="로드맵에 항목이 없습니다")
        
        first_item = items[0]
        start_date = first_item.get("created_at")
        if not start_date:
            raise HTTPException(status_code=400, detail="시작일을 찾을 수 없습니다")
        
        # 오늘이 몇 일차인지 계산
        today = datetime.utcnow()
        days_diff = (today - start_date).days + 1  # 1일차부터 시작
        
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


@app.patch("/roadmaps/items/{roadmap_item_id}")
async def update_roadmap_item(roadmap_item_id: str, request: UpdateRoadmapItemRequest):
    """로드맵 항목의 완료 상태 업데이트
    
    roadmap_item_id 형식: 
    - "roadmap_id:day_index:task_index" (새 구조: tasks 배열 내 개별 task)
    - "roadmap_id:item_index" (레거시: items 배열 직접)
    """
    try:
        from bson import ObjectId
        
        parts = roadmap_item_id.split(":")
        
        if len(parts) == 3:
            # 새 구조: roadmap_id:day_index:task_index
            roadmap_id_str, day_index_str, task_index_str = parts
            try:
                from bson.errors import InvalidId
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
            
            # tasks 배열 내 특정 task 업데이트
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
                from bson.errors import InvalidId
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
        
        # 성공 응답
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


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket 기반 채팅 엔드포인트"""
    await websocket.accept()
    session_id = None
    
    try:
        while True:
            # 클라이언트로부터 메시지 수신
            data = await websocket.receive_text()
            
            try:
                # JSON 파싱
                request_data = json.loads(data)
                message = request_data.get("message", "")
                
                if not message:
                    await websocket.send_json({
                        "type": "error",
                        "error": "메시지가 비어있습니다."
                    })
                    continue
                
                # 세션 ID 처리
                session_id = request_data.get("session_id")
                if not session_id:
                    session_id = str(uuid.uuid4())
                    await websocket.send_json({
                        "type": "session",
                        "session_id": session_id
                    })
                
                # WebSocket 연결을 세션에 매핑
                active_connections[session_id] = websocket
                
                # JWT 토큰에서 user_id 추출 (WebSocket에서는 쿼리 파라미터나 메시지에서 받음)
                # 클라이언트가 WebSocket 메시지에 token을 포함시킬 수 있음
                user_id_from_token = None
                token = request_data.get("token") or request_data.get("authorization")
                if token:
                    # "Bearer " 접두사 제거
                    if token.startswith("Bearer "):
                        token = token.replace("Bearer ", "").strip()
                    # JWT 토큰 파싱
                    try:
                        jwt_secret = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
                        import base64
                        parts = token.split('.')
                        if len(parts) == 3:
                            payload = parts[1]
                            payload += '=' * (4 - len(payload) % 4)
                            decoded = json.loads(base64.urlsafe_b64decode(payload))
                            user_id_from_token = decoded.get("user_id") or decoded.get("sub")
                            print(f"🔍 [WebSocket Debug] JWT에서 user_id 추출: {user_id_from_token}")
                    except Exception as e:
                        print(f"⚠️ [WebSocket Debug] JWT 파싱 실패: {e}")
                
                # 로드맵 모드 확인 및 모델 ID 결정
                config = await get_session_config(session_id)
                user_id = request_data.get("user_id") or user_id_from_token
                
                # 세션 설정이 없으면 생성
                if not config and (user_id or session_id):
                    try:
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
                        print(f"✨ [WebSocket] 새 세션 설정 생성: {session_id} (User: {user_id})")
                    except Exception as e:
                        print(f"⚠️ [WebSocket] 세션 설정 생성 중 오류: {e}")

                # user_id 우선순위: 세션 설정의 user_id > request_data의 user_id
                user_id_for_save = None
                if config and config.get("user_id"):
                    user_id_for_save = str(config["user_id"])
                elif user_id:
                    user_id_for_save = user_id
                
                if config and config.get("mode") == "roadmap":
                    # 로드맵 모드일 때는 소넷 사용
                    model_id = ROADMAP_MODEL_ID
                    rag_context = ""  # 로드맵 모드에서는 RAG 사용 안 함
                elif message.startswith("[오늘 로드맵 질문]"):
                    # 로드맵 질문 모드
                    model_id = ROADMAP_MODEL_ID
                    rag_context = ""  # 컨텍스트가 메시지에 포함되어 있음
                    print(f"📚 [WebSocket] 로드맵 질문 감지됨 - 모델 ID: {model_id}")
                else:
                    # 일반 채팅 모드일 때는 요청된 모델 ID 또는 기본값(하이쿠) 사용
                    model_id = request_data.get("model_id", DEFAULT_MODEL_ID)
                    # RAG 컨텍스트 생성 (일반 채팅 모드에서만)
                    rag_context = await get_rag_context(
                        query=message,
                        session_id=session_id,
                        user_id=user_id_for_save,
                        limit=5
                    )
                
                max_tokens = request_data.get("max_tokens", 4096)
                temperature = request_data.get("temperature", 0.7)
                
                # 시스템 프롬프트 가져오기 (RAG 컨텍스트 포함)
                if message.startswith("[오늘 로드맵 질문]"):
                    system_prompt = ROADMAP_QA_SYSTEM_PROMPT
                else:
                    system_prompt = await get_system_prompt(session_id, rag_context=rag_context)
                
                # 대화 히스토리 가져오기 (MongoDB에서 조회)
                messages = []
                if request_data.get("conversation_history"):
                    # 클라이언트에서 제공한 히스토리 사용
                    for msg in request_data["conversation_history"]:
                        if isinstance(msg, dict) and "role" in msg and "content" in msg:
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })
                else:
                    # MongoDB에서 세션의 최근 메시지 조회
                    stored_messages = await get_conversation_messages(session_id, limit=50)
                    for msg in stored_messages:
                        if isinstance(msg, dict) and "role" in msg and "content" in msg:
                            messages.append({
                                "role": msg["role"],
                                "content": msg["content"]
                            })
                
                # 현재 사용자 메시지 추가
                messages.append({
                    "role": "user",
                    "content": message,
                })
                
                # 사용자 메시지를 백그라운드에서 저장 (non-blocking)
                asyncio.create_task(save_conversation_message(
                    session_id=session_id,
                    role="user",
                    content=message,
                    user_id=user_id_for_save
                ))
                
                # Bedrock 요청 페이로드 구성
                body = json.dumps(
                    {
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "system": system_prompt,
                        "messages": messages,
                    }
                )
                
                # Bedrock API 스트리밍 호출
                response = bedrock_runtime.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=body,
                )
                
                # 스트리밍 응답 처리
                assistant_message = ""
                stream = response.get('body')
                
                if stream:
                    for event in stream:
                        try:
                            # Bedrock 스트리밍 이벤트 구조 확인
                            if 'chunk' in event:
                                chunk_data = event['chunk']
                                if 'bytes' in chunk_data:
                                    chunk = json.loads(chunk_data['bytes'].decode())
                                else:
                                    chunk = chunk_data
                                
                                # delta에 텍스트가 있으면 전송
                                if 'delta' in chunk and 'text' in chunk['delta']:
                                    text_chunk = chunk['delta']['text']
                                    assistant_message += text_chunk
                                    
                                    # 각 청크를 클라이언트에 전송
                                    await websocket.send_json({
                                        "type": "chunk",
                                        "text": text_chunk,
                                        "session_id": session_id,
                                    })
                                    print(f"[Streaming] Sent chunk: {text_chunk[:50]}...")  # 디버깅
                        except Exception as e:
                            print(f"[Streaming] Error processing chunk: {e}")
                            print(f"[Streaming] Event structure: {event}")
                            continue
                
                # 스트리밍 완료 후 전체 메시지 저장
                if assistant_message:
                    # 로드맵 모드이고 JSON 로드맵이 포함되어 있으면 저장
                    if config and config.get("mode") == "roadmap":
                        print(f"🔍 [Roadmap WebSocket] 로드맵 모드 감지됨. 응답에서 JSON 검색 중...")
                        print(f"🔍 [Roadmap WebSocket] 응답 길이: {len(assistant_message)} 문자")
                        
                        import re
                        json_str = None
                        
                        # 패턴 1: ```json ... ``` (가장 우선)
                        json_match = re.search(r'```json\s*([\s\S]*?)\s*```', assistant_message)
                        if json_match:
                            json_str = json_match.group(1)
                            print(f"✅ [Roadmap WebSocket] JSON 블록 발견 (```json 형식)")
                        else:
                            # 패턴 2: ``` ... ``` (json 없이)
                            json_match = re.search(r'```\s*([\s\S]*?)\s*```', assistant_message)
                            if json_match:
                                json_str = json_match.group(1)
                                print(f"✅ [Roadmap WebSocket] JSON 블록 발견 (``` 형식)")
                            else:
                                # 패턴 3: { ... } 전체 JSON 객체 찾기 (중괄호 매칭)
                                # "roadmap" 키워드가 있는 첫 번째 { 부터 시작해서 중괄호가 모두 닫힐 때까지 추출
                                roadmap_start = assistant_message.find('"roadmap"')
                                if roadmap_start != -1:
                                    # "roadmap" 앞에서 { 찾기
                                    brace_start = assistant_message.rfind('{', 0, roadmap_start)
                                    if brace_start != -1:
                                        # 중괄호 매칭으로 전체 JSON 추출
                                        brace_count = 0
                                        brace_end = brace_start
                                        for i in range(brace_start, len(assistant_message)):
                                            if assistant_message[i] == '{':
                                                brace_count += 1
                                            elif assistant_message[i] == '}':
                                                brace_count -= 1
                                                if brace_count == 0:
                                                    brace_end = i + 1
                                                    break
                                        
                                        if brace_count == 0:
                                            json_str = assistant_message[brace_start:brace_end]
                                            print(f"✅ [Roadmap WebSocket] JSON 객체 발견 (중괄호 매칭)")
                        
                        if json_str:
                            try:
                                # JSON 문자열 정리 (앞뒤 공백 제거)
                                json_str = json_str.strip()
                                print(f"🔍 [Roadmap WebSocket] JSON 문자열 길이: {len(json_str)}")
                                
                                # JSON 주석 제거 (// 주석 및 /* */ 주석)
                                import re
                                # // 주석 제거 (문자열 내부가 아닌 경우)
                                json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
                                # /* */ 주석 제거
                                json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
                                # 빈 줄 제거
                                json_str = re.sub(r'\n\s*\n', '\n', json_str)
                                # 앞뒤 공백 다시 제거
                                json_str = json_str.strip()
                                
                                print(f"🔍 [Roadmap WebSocket] 주석 제거 후 JSON 문자열 길이: {len(json_str)}")
                                
                                # JSON 파싱
                                roadmap_data = json.loads(json_str)
                                print(f"✅ [Roadmap WebSocket] JSON 파싱 성공")
                                
                                # roadmap 필드 확인
                                if roadmap_data.get("roadmap") and isinstance(roadmap_data.get("roadmap"), list):
                                    print(f"✅ [Roadmap WebSocket] roadmap 배열 확인됨 (길이: {len(roadmap_data.get('roadmap', []))})")
                                    
                                    # user_id 우선순위: 세션 설정의 user_id > request_data의 user_id
                                    if not user_id_for_save:
                                        if config and config.get("user_id"):
                                            user_id_for_save = str(config["user_id"])
                                        elif user_id:
                                            user_id_for_save = user_id
                                    
                                    print(f"💾 [Roadmap WebSocket] 로드맵 저장 시작 - session_id: {session_id}, user_id: {user_id_for_save}")
                                    
                                    # total_days가 있고, 현재 생성된 일차보다 크면 배치 생성 수행
                                    total_days = roadmap_data.get("total_days", 0)
                                    current_items = len(roadmap_data.get("roadmap", []))
                                    
                                    if total_days > current_items and total_days > 30:
                                        print(f"🔄 [Roadmap WebSocket] 배치 생성 필요: total_days={total_days}, current_items={current_items}")
                                        # 나머지 일차 생성
                                        full_roadmap = await generate_full_roadmap(
                                            roadmap_info=roadmap_data,
                                            session_id=session_id,
                                            user_id=user_id_for_save
                                        )
                                        if full_roadmap:
                                            roadmap_data = full_roadmap
                                            print(f"✅ [Roadmap WebSocket] 배치 생성 완료: {len(roadmap_data.get('roadmap', []))}일")
                                    
                                    result = await save_roadmap(roadmap_data, session_id, user_id_for_save)
                                    
                                    if result:
                                        print(f"✅ [Roadmap WebSocket] 로드맵 저장 완료: {roadmap_data.get('name', '로드맵')}, _id: {result.get('_id')}, user_id: {user_id_for_save}")
                                        roadmap_saved_ws = True
                                        
                                        # Day 1 상세 자동 생성 (백그라운드)
                                        roadmap_id = str(result.get('_id'))
                                        goal = roadmap_data.get('name', '학습')
                                        asyncio.create_task(generate_day_details(roadmap_id, 1, goal))
                                        print(f"📝 [Roadmap WebSocket] Day 1 상세 생성 요청됨 (백그라운드)")
                                        
                                        # JSON 부분을 제거하고 간단한 메시지로 대체
                                        roadmap_name = roadmap_data.get('name', '로드맵')
                                        total_items = len(roadmap_data.get('roadmap', []))
                                        assistant_message = f"✅ 로드맵 '{roadmap_name}'이 생성되었습니다! ({total_items}일) 로드맵 목록에서 확인하실 수 있습니다."
                                    else:
                                        print(f"❌ [Roadmap WebSocket] 로드맵 저장 실패: save_roadmap이 None 반환")
                                else:
                                    print(f"⚠️ [Roadmap WebSocket] roadmap 필드가 없거나 배열이 아님")
                                    print(f"🔍 [Roadmap WebSocket] roadmap 필드 값: {roadmap_data.get('roadmap')}")
                            except json.JSONDecodeError as e:
                                print(f"❌ [Roadmap WebSocket] JSON 파싱 실패: {e}")
                                print(f"🔍 [Roadmap WebSocket] 문제가 있는 JSON 문자열 (처음 500자): {json_str[:500]}")
                                print(f"🔍 [Roadmap WebSocket] 문제가 있는 JSON 문자열 (마지막 500자): {json_str[-500:]}")
                                import traceback
                                traceback.print_exc()
                            except Exception as e:
                                print(f"❌ [Roadmap WebSocket] 로드맵 저장 중 오류: {e}")
                                import traceback
                                traceback.print_exc()
                        else:
                            print(f"⚠️ [Roadmap WebSocket] 응답에서 JSON을 찾을 수 없음")
                            print(f"🔍 [Roadmap WebSocket] 전체 응답: {assistant_message}")
                    else:
                        if not config:
                            print(f"⚠️ [Roadmap WebSocket] config가 None입니다")
                        elif config.get("mode") != "roadmap":
                            print(f"⚠️ [Roadmap WebSocket] 모드가 'roadmap'이 아님: {config.get('mode')}")
                    
                    # AI 응답을 백그라운드에서 저장 (non-blocking)
                    asyncio.create_task(save_conversation_message(
                        session_id=session_id,
                        role="assistant",
                        content=assistant_message,
                        user_id=user_id_for_save
                    ))
                    
                    # AI 응답을 히스토리에 추가 (이미 MongoDB에 저장됨)
                    messages.append({
                        "role": "assistant",
                        "content": assistant_message,
                    })
                    
                    # 히스토리는 MongoDB에서 관리하므로 메모리 기반 저장 제거
                    
                    # 스트리밍 완료 신호 전송
                    await websocket.send_json({
                        "type": "message",
                        "response": assistant_message,
                        "model_id": model_id,
                        "session_id": session_id,
                    })
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "error": "잘못된 JSON 형식입니다."
                })
            except Exception as e:
                await websocket.send_json({
                    "type": "error",
                    "error": f"처리 중 오류가 발생했습니다: {str(e)}"
                })
                
    except WebSocketDisconnect:
        if session_id and session_id in active_connections:
            del active_connections[session_id]
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "error": f"연결 오류: {str(e)}"
            })
        except:
            pass
        if session_id and session_id in active_connections:
            del active_connections[session_id]
