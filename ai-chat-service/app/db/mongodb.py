
import asyncio
from typing import Optional
from datetime import datetime
from pymongo import AsyncMongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.config import settings
from app.core.prompts import BETAIN_PROMPT, ALPAIN_PROMPT, CLEMENTINE_PROMPT

# MongoDB 클라이언트 (전역)
_client: Optional[AsyncMongoClient] = None
_db: Optional[Database] = None


async def get_client() -> AsyncMongoClient:
    """MongoDB 클라이언트 가져오기 (싱글톤)"""
    global _client
    if _client is None:
        _client = AsyncMongoClient(settings.MONGO_URI)
        print(f"✅ MongoDB 클라이언트 연결 완료: {settings.MONGO_HOST}")
    return _client


async def get_database() -> Database:
    """MongoDB 데이터베이스 가져오기"""
    global _db
    if _db is None:
        client = await get_client()
        _db = client[settings.MONGO_DB_NAME]
    return _db


async def get_collection(collection_name: str) -> Collection:
    """컬렉션 가져오기"""
    db = await get_database()
    return db[collection_name]


async def init_db():
    """데이터베이스 초기화 및 기본 데이터 삽입"""
    try:
        db = await get_database()
        
        # 컬렉션 인덱스 생성
        # conversation_messages 컬렉션 인덱스
        conversation_messages = await get_collection("conversation_messages")
        await conversation_messages.create_index("session_id")
        await conversation_messages.create_index("user_id")
        await conversation_messages.create_index("created_at")
        
        # 벡터 검색 인덱스는 별도 스크립트로 생성하거나 Atlas에서 설정
        
        print("✅ conversation_messages 인덱스 생성 완료")
        
        # session_configs 컬렉션 인덱스
        session_configs = await get_collection("session_configs")
        await session_configs.create_index("session_id", unique=True)
        await session_configs.create_index("user_id")
        print("✅ session_configs 인덱스 생성 완료")
        
        # roadmaps 컬렉션 인덱스
        roadmaps = await get_collection("roadmaps")
        await roadmaps.create_index("user_id")
        await roadmaps.create_index("session_id")
        await roadmaps.create_index("created_at")
        print("✅ roadmaps 인덱스 생성 완료")
        
        # personalities 컬렉션 인덱스 및 기본 데이터
        personalities = await get_collection("personalities")
        await personalities.create_index("name", unique=True)
        
        # 이미 데이터가 있는지 확인
        count = await personalities.count_documents({})
        if count > 0:
            print("ℹ️ personalities 데이터가 이미 존재합니다.")
            return
        
        # 성격 캐릭터 데이터 삽입
        personalities_data = [
            {
                "name": "베타인",
                "description": "상냥하고 사려 깊은 여자 캐릭터",
                "system_prompt": BETAIN_PROMPT,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "name": "알파인",
                "description": "까칠한 소꿉친구 매스가키 캐릭터",
                "system_prompt": ALPAIN_PROMPT,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
            {
                "name": "클레맨타인",
                "description": "정보 전문가 캐릭터",
                "system_prompt": CLEMENTINE_PROMPT,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            },
        ]
        
        await personalities.insert_many(personalities_data)
        print("✅ personalities 기본 데이터 삽입 완료")
        
    except Exception as e:
        print(f"❌ 데이터베이스 초기화 중 오류: {e}")
        import traceback
        traceback.print_exc()
        # raise  # 실패해도 서버는 켜지게 할지? 원본은 raise 함
        raise


async def close_db():
    """MongoDB 연결 종료"""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        print("✅ MongoDB 연결 종료")


def run_async(coro):
    """비동기 함수를 동기적으로 실행"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)
