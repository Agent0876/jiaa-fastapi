#!/usr/bin/env python3
"""
Jiaa AI Chat Service API 테스트 스크립트
"""
import requests
import json
import uuid

BASE_URL = "http://localhost:8000"

def print_response(title, response):
    """응답 출력"""
    print(f"\n{'='*60}")
    print(f"📌 {title}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except:
        print(f"Response: {response.text}")
    print()

def test_health():
    """헬스 체크"""
    print("1️⃣ 헬스 체크 테스트")
    response = requests.get(f"{BASE_URL}/health")
    print_response("Health Check", response)
    return response.status_code == 200

def test_root():
    """루트 엔드포인트"""
    print("2️⃣ 루트 엔드포인트 테스트")
    response = requests.get(f"{BASE_URL}/")
    print_response("Root", response)
    return response.status_code == 200

def test_get_personalities():
    """성격 목록 조회"""
    print("3️⃣ 성격 캐릭터 목록 조회")
    response = requests.get(f"{BASE_URL}/personalities")
    print_response("Get Personalities", response)
    if response.status_code == 200:
        personalities = response.json()
        print(f"✅ {len(personalities)}개의 성격을 찾았습니다:")
        for p in personalities:
            print(f"   - {p['name']}: {p.get('description', 'N/A')}")
        return personalities
    return None

def test_select_personality(personality_id, session_id=None):
    """성격 선택"""
    print("4️⃣ 성격 선택 테스트")
    if not session_id:
        session_id = str(uuid.uuid4())
    
    data = {
        "session_id": session_id,
        "personality_id": personality_id,
        "user_id": None  # 선택사항
    }
    response = requests.post(f"{BASE_URL}/personalities/select", json=data)
    print_response("Select Personality", response)
    return session_id if response.status_code == 200 else None

def test_start_roadmap(session_id=None):
    """로드맵 모드 시작"""
    print("5️⃣ 로드맵 생성 모드 시작")
    if not session_id:
        session_id = str(uuid.uuid4())
    
    data = {
        "session_id": session_id,
        "user_id": None  # 선택사항
    }
    response = requests.post(f"{BASE_URL}/chat/roadmap/start", json=data)
    print_response("Start Roadmap", response)
    return session_id if response.status_code == 200 else None

def test_chat(session_id, message, user_id=None):
    """채팅 테스트"""
    print(f"6️⃣ 채팅 테스트: '{message}'")
    data = {
        "message": message,
        "session_id": session_id,
        "user_id": user_id
    }
    response = requests.post(f"{BASE_URL}/chat", json=data)
    print_response("Chat", response)
    if response.status_code == 200:
        result = response.json()
        print(f"💬 AI 응답: {result.get('response', 'N/A')[:100]}...")
        return result.get('session_id')
    return None

def test_get_user_sessions(user_id):
    """사용자별 세션 조회"""
    print("7️⃣ 사용자별 세션 조회")
    response = requests.get(f"{BASE_URL}/sessions/user/{user_id}")
    print_response("Get User Sessions", response)
    return response.status_code == 200

def main():
    """메인 테스트 함수"""
    print("🚀 Jiaa AI Chat Service API 테스트 시작")
    print(f"📍 Base URL: {BASE_URL}\n")
    
    # 기본 테스트
    if not test_health():
        print("❌ 서버가 실행 중이 아닙니다. 먼저 서버를 시작하세요:")
        print("   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        return
    
    test_root()
    
    # 성격 목록 조회
    personalities = test_get_personalities()
    if not personalities:
        print("❌ 성격 목록을 가져올 수 없습니다.")
        return
    
    # 첫 번째 성격 선택
    personality_id = personalities[0]['id']
    session_id = test_select_personality(personality_id)
    
    if session_id:
        # 채팅 테스트
        test_chat(session_id, "안녕하세요!")
        test_chat(session_id, "파이썬을 배우고 싶어요")
    
    # 로드맵 모드 테스트
    roadmap_session = test_start_roadmap()
    if roadmap_session:
        test_chat(roadmap_session, "로드맵을 만들어주세요")
    
    print("\n" + "="*60)
    print("✅ 테스트 완료!")
    print("="*60)
    print("\n💡 추가 테스트:")
    print(f"   - 브라우저에서 API 문서 확인: {BASE_URL}/docs")
    print(f"   - 대체 문서: {BASE_URL}/redoc")
    print(f"   - WebSocket 테스트: ws://localhost:8000/ws/chat")

if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("❌ 서버에 연결할 수 없습니다.")
        print("   서버가 실행 중인지 확인하세요:")
        print("   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

