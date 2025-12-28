#!/usr/bin/env python3
"""
WebSocket 채팅 테스트 스크립트
"""
import asyncio
import json
import websockets
import sys

async def test_websocket():
    uri = "ws://localhost:8000/ws/chat"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✅ WebSocket 연결 성공: {uri}\n")
            
            # 테스트 메시지 전송
            test_message = {
                "message": "안녕하세요! 테스트 메시지입니다.",
                "session_id": "test-session-123",
                "user_id": "test-user-456",
                "model_id": "anthropic.claude-3-haiku-20240307-v1:0",
                "max_tokens": 4096,
                "temperature": 0.7
            }
            
            print(f"📤 전송: {json.dumps(test_message, ensure_ascii=False, indent=2)}\n")
            await websocket.send(json.dumps(test_message))
            
            # 응답 수신
            print("⏳ 응답 대기 중...\n")
            response = await websocket.recv()
            data = json.loads(response)
            
            print(f"📥 수신: {json.dumps(data, ensure_ascii=False, indent=2)}")
            
            # 추가 메시지 전송 (대화 계속)
            if data.get("type") == "message":
                print("\n" + "="*50)
                follow_up = {
                    "message": "Python으로 웹 개발을 배우고 싶어요",
                    "session_id": "test-session-123"
                }
                print(f"📤 추가 전송: {json.dumps(follow_up, ensure_ascii=False, indent=2)}\n")
                await websocket.send(json.dumps(follow_up))
                
                response2 = await websocket.recv()
                data2 = json.loads(response2)
                print(f"📥 수신: {json.dumps(data2, ensure_ascii=False, indent=2)}")
            
    except websockets.exceptions.ConnectionRefused:
        print(f"❌ 연결 실패: 서버가 실행 중이지 않습니다. {uri}")
        print("   uvicorn app.main:app --reload")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    print("🚀 WebSocket 채팅 테스트 시작\n")
    asyncio.run(test_websocket())

