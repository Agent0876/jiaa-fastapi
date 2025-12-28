# Jiaa AI Chat Service 테스트 가이드

## 🚀 서버 실행

```bash
cd ai-chat-service


```

## 📋 테스트 방법

### 1. 자동 테스트 스크립트 사용

```bash
# requests 라이브러리 설치 (필요한 경우)
pip install requests

# 테스트 실행
python test_api.py
```

### 2. curl을 사용한 수동 테스트

#### 헬스 체크
```bash
curl http://localhost:8000/health
```

#### 성격 목록 조회
```bash
curl http://localhost:8000/personalities
```

#### 성격 선택
```bash
curl -X POST http://localhost:8000/personalities/select \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test-session-123",
    "personality_id": 1
  }'
```

#### 채팅
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "안녕하세요!",
    "session_id": "test-session-123"
  }'
```

#### 로드맵 모드 시작
```bash
curl -X POST http://localhost:8000/chat/roadmap/start \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "roadmap-session-123"
  }'
```

#### 사용자별 세션 조회
```bash
curl http://localhost:8000/sessions/user/{user_id}
```

### 3. FastAPI 자동 문서 사용

서버 실행 후 브라우저에서 접속:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

이 문서에서 모든 API를 테스트할 수 있습니다!

### 4. Python requests 사용

```python
import requests

BASE_URL = "http://localhost:8000"

# 성격 목록 조회
response = requests.get(f"{BASE_URL}/personalities")
print(response.json())

# 채팅
response = requests.post(f"{BASE_URL}/chat", json={
    "message": "안녕하세요!",
    "session_id": "test-123"
})
print(response.json())
```

## 🔌 WebSocket 테스트

WebSocket 클라이언트를 사용하거나 Python으로 테스트:

```python
import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as websocket:
        # 메시지 전송
        message = {
            "message": "안녕하세요!",
            "session_id": "ws-test-123"
        }
        await websocket.send(json.dumps(message))
        
        # 응답 수신
        response = await websocket.recv()
        print(json.loads(response))

asyncio.run(test_websocket())
```

## 📝 주요 API 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/` | 서비스 상태 확인 |
| GET | `/health` | 헬스 체크 |
| GET | `/personalities` | 성격 캐릭터 목록 조회 |
| POST | `/personalities/select` | 성격 선택 |
| POST | `/chat` | 일반 채팅 |
| POST | `/chat/roadmap/start` | 로드맵 생성 모드 시작 |
| POST | `/chat/clear` | 세션 히스토리 삭제 |
| GET | `/sessions/user/{user_id}` | 사용자별 세션 목록 |
| WebSocket | `/ws` | WebSocket 채팅 |

## 🎯 테스트 시나리오

1. **기본 흐름**
   - 성격 목록 조회 → 성격 선택 → 채팅

2. **로드맵 생성**
   - 로드맵 모드 시작 → 질문에 답변 → 로드맵 생성

3. **사용자별 세션 관리**
   - user_id와 함께 채팅 → 사용자별 세션 조회

