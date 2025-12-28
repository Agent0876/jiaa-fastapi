"""
MongoDB Vector Search 인덱스 생성 스크립트

이 스크립트는 MongoDB 6.0.11+에서 벡터 검색 인덱스를 생성합니다.
Docker로 MongoDB를 실행하는 경우 이 스크립트를 사용하여 인덱스를 생성할 수 있습니다.

주의: MongoDB 6.0.11 이상 버전이 필요합니다.
"""

import os
import sys
from pymongo import MongoClient
from database import MONGO_URI, MONGO_DB_NAME

def create_vector_index():
    """
    MongoDB 6.0.11+에서 벡터 검색 인덱스 생성
    
    주의: MongoDB 6.0.11 이상 버전이 필요합니다.
    """
    try:
        print(f"🔗 MongoDB 연결 중: {MONGO_URI.replace(MONGO_URI.split('@')[-1] if '@' in MONGO_URI else '', '***')}")
        
        # 동기 클라이언트 사용 (createSearchIndexes는 동기 명령)
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB_NAME]
        
        # MongoDB 버전 확인
        server_info = client.server_info()
        version = server_info.get("version", "unknown")
        print(f"📦 MongoDB 버전: {version}")
        
        major_version = int(version.split('.')[0])
        minor_version = int(version.split('.')[1]) if len(version.split('.')) > 1 else 0
        
        if major_version < 6 or (major_version == 6 and minor_version < 0):
            print(f"⚠️ MongoDB 6.0.11 이상 버전이 필요합니다. 현재 버전: {version}")
            print("💡 MongoDB 6.0.11+ Docker 이미지를 사용하세요:")
            print("   docker run -d --name mongodb -p 27017:27017 mongo:6.0.11")
            client.close()
            return False
        
        # createSearchIndexes 명령 실행
        print("🔨 벡터 검색 인덱스 생성 중...")
        result = db.command({
            "createSearchIndexes": "conversation_messages",
            "indexes": [
                {
                    "name": "vector_index",
                    "definition": {
                        "mappings": {
                            "dynamic": False,
                            "fields": {
                                "embedding": {
                                    "type": "knnVector",
                                    "dimensions": 768,  # ko-sroberta-multitask 모델의 차원
                                    "similarity": "cosine"
                                }
                            }
                        }
                    }
                }
            ]
        })
        
        print(f"✅ 벡터 인덱스 생성 완료!")
        print(f"   인덱스 ID: {result.get('id', 'N/A')}")
        print(f"   인덱스 이름: vector_index")
        print(f"   차원: 768 (ko-sroberta-multitask)")
        print(f"   유사도: cosine")
        print("\n💡 인덱스가 활성화되기까지 몇 초 걸릴 수 있습니다.")
        
        client.close()
        return True
        
    except Exception as e:
        error_msg = str(e)
        print(f"❌ 벡터 인덱스 생성 실패: {error_msg}")
        
        if "not authorized" in error_msg.lower():
            print("💡 인증 오류: MONGO_USER와 MONGO_PASSWORD를 확인하세요.")
        elif "command not found" in error_msg.lower() or "unknown command" in error_msg.lower():
            print("💡 MongoDB 6.0.11 이상 버전이 필요합니다.")
            print("   Docker 명령어: docker run -d --name mongodb -p 27017:27017 mongo:6.0.11")
        elif "already exists" in error_msg.lower():
            print("✅ 인덱스가 이미 존재합니다.")
            return True
        else:
            print("💡 MongoDB 연결 정보를 확인하세요.")
        
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("MongoDB Vector Search 인덱스 생성 스크립트")
    print("=" * 60)
    print()
    
    success = create_vector_index()
    
    if success:
        print("\n✅ 인덱스 생성이 완료되었습니다!")
        print("이제 MongoDB Atlas Vector Search를 사용할 수 있습니다.")
    else:
        print("\n⚠️ 인덱스 생성에 실패했습니다.")
        print("애플리케이션은 폴백 모드(애플리케이션 레벨 검색)로 작동합니다.")
    
    sys.exit(0 if success else 1)

