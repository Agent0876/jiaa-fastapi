
import os
import jwt
import json
import uuid
import base64
from typing import Optional
from fastapi import Header

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
        # 주의: 실제 운영 환경에서는 검증이 필요하지만, 여기서는 단순히 payload를 읽기만 함
        try:
            decoded = jwt.decode(token, jwt_secret, algorithms=["HS256"], options={"verify_signature": False})
            print(f"✅ [JWT Debug] JWT 디코딩 성공 (검증 없이)")
        except jwt.DecodeError as e:
            print(f"⚠️ [JWT Debug] JWT 디코딩 실패, payload만 읽기 시도: {e}")
            # 검증 실패 시 payload만 읽기
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
