import json
import os
import socket
from typing import Literal, Optional

import boto3
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from py_eureka_client import eureka_client

app = FastAPI(
    title="AI Judge Service",
    version="1.0.0",
    description="창 제목을 분석하여 공부/오락 판단하는 AI 판사 서비스"
)

# CORS Settings
# Gateway를 통해 접근할 때는 Gateway에서 CORS를 처리하므로
# FastAPI의 CORS 미들웨어는 비활성화 (중복 헤더 방지)
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Development environment: allow all
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# Bedrock 클라이언트 초기화
bedrock_runtime = boto3.client(
    service_name="bedrock-runtime",
    region_name=os.getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
)

# 기본 모델 ID
DEFAULT_MODEL_ID = os.getenv("DEFAULT_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0")

# AI 판사 프롬프트
JUDGE_SYSTEM_PROMPT = """당신은 사용자의 학습 활동을 판단하는 AI 판사입니다.

주어진 창 제목과 프로세스 이름을 분석하여 다음 중 하나로 판단하세요:
- STUDY: 공부/학습 관련 활동 (강의, 문서, 코딩, 학습 사이트 등)
- DISTRACTION: 놀이/오락 관련 활동 (게임, 유튜브, SNS, 영화 등)

판단 기준:
1. 명확한 학습 관련 키워드가 있으면 STUDY
2. 명확한 오락 관련 키워드가 있으면 DISTRACTION
3. 게임 프로세스 이름(예: league, lol, valorant, overwatch, steam 등)이면 DISTRACTION
4. 애매한 경우 맥락을 고려하여 판단
5. 코딩, 개발, 프로그래밍 관련은 STUDY
6. 게임, 영상 시청, SNS는 DISTRACTION

응답은 반드시 다음 JSON 형식으로만 출력하세요:
{
    "verdict": "STUDY" 또는 "DISTRACTION",
    "reason": "판단 이유 (한국어로 간단히)",
    "confidence": 0.0~1.0 사이의 숫자
}"""

# 요청 모델
class JudgeRequest(BaseModel):
    window_title: str
    process_name: Optional[str] = None  # 프로세스 이름 (게임 감지용)

# 응답 모델
class JudgeResponse(BaseModel):
    verdict: Literal["STUDY", "DISTRACTION"]
    reason: str
    confidence: float = 0.0  # 신뢰도 (0.0 ~ 1.0)


def fallback_judge(window_title: str, ai_response: str = "") -> dict:
    """
    Bedrock API 실패 시 최소한의 판단 (AI 응답 기반 또는 기본값)
    하드코딩된 키워드는 제거하고 AI만 사용
    """
    # AI 응답이 있으면 그걸 사용
    if ai_response:
        # AI 응답에서 STUDY/DISTRACTION 찾기
        if "STUDY" in ai_response.upper() or "공부" in ai_response:
            return {
                "verdict": "STUDY",
                "reason": "AI 응답 기반 판단",
                "confidence": 0.5
            }
        elif "DISTRACTION" in ai_response.upper() or "오락" in ai_response or "놀이" in ai_response or "게임" in ai_response:
            return {
                "verdict": "DISTRACTION",
                "reason": "AI 응답 기반 판단",
                "confidence": 0.5
            }
    
    # 기본값: 공부로 간주 (보수적 접근)
    return {
        "verdict": "STUDY",
        "reason": "AI API 실패, 기본값으로 공부로 간주",
        "confidence": 0.3
    }


def judge_window_title(window_title: str, process_name: Optional[str] = None) -> dict:
    """
    창 제목과 프로세스 이름을 분석하여 공부/오락 판단
    """
    if (not window_title or len(window_title.strip()) == 0) and (not process_name or len(process_name.strip()) == 0):
        return {
            "verdict": "STUDY",
            "reason": "창 제목과 프로세스 이름이 없어 공부로 간주",
            "confidence": 0.5
        }
    
    # Bedrock API 호출
    try:
        process_info = f"\n프로세스 이름: \"{process_name}\"" if process_name else ""
        prompt = f"""창 제목: "{window_title}"{process_info}

이 창 제목과 프로세스 이름을 분석하여 공부 관련인지, 놀이/오락 관련인지 판단해주세요."""
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "temperature": 0.3,  # 낮은 temperature로 일관성 있는 판단
            "system": JUDGE_SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        })
        
        response = bedrock_runtime.invoke_model(
            modelId=DEFAULT_MODEL_ID,
            body=body
        )
        
        response_body = json.loads(response.get("body").read())
        assistant_message = response_body.get("content", [])[0].get("text", "")
        
        # JSON 파싱 시도
        try:
            # 응답에서 JSON 추출
            json_start = assistant_message.find("{")
            json_end = assistant_message.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                json_str = assistant_message[json_start:json_end]
                result = json.loads(json_str)
                
                # 검증
                if result.get("verdict") in ["STUDY", "DISTRACTION"]:
                    return {
                        "verdict": result["verdict"],
                        "reason": result.get("reason", "AI 판단"),
                        "confidence": float(result.get("confidence", 0.7))
                    }
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[Judge] JSON 파싱 실패: {e}, 응답: {assistant_message}")
        
        # JSON 파싱 실패 시 텍스트에서 키워드 기반 판단
        return fallback_judge(window_title, assistant_message)
        
    except Exception as e:
        print(f"[Judge] Bedrock API 오류: {e}")
        # API 실패 시 키워드 기반 판단
        return fallback_judge(window_title, "")


@app.get("/")
def read_root():
    return {"service": "ai-judge-service", "status": "running"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "model": DEFAULT_MODEL_ID}


@app.on_event("startup")
async def startup_event():
    """Register with Eureka on startup"""
    try:
        eureka_server = os.getenv("EUREKA_SERVER", "http://discovery-service:8761/eureka")
        app_name = os.getenv("EUREKA_APP_NAME", "ai-judge-service")
        port = int(os.getenv("PORT", "8080"))
        
        # Get hostname (for Kubernetes)
        hostname = os.getenv("HOSTNAME", socket.gethostname())
        ip_address = os.getenv("POD_IP", socket.gethostbyname(hostname))
        
        await eureka_client.init_async(
            eureka_server=eureka_server,
            app_name=app_name,
            instance_port=port,
            instance_host=ip_address,
            instance_ip=ip_address,
            renewal_interval_in_secs=30,
            duration_in_secs=90,
        )
        print(f"✅ Registered with Eureka: {app_name} at {ip_address}:{port}")
    except Exception as e:
        print(f"⚠️ Eureka registration error: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Deregister from Eureka on shutdown"""
    try:
        await eureka_client.stop_async()
        print("✅ Deregistered from Eureka")
    except Exception as e:
        print(f"⚠️ Eureka deregistration error: {e}")


@app.post("/judge", response_model=JudgeResponse)
async def judge_window(request: JudgeRequest):
    """
    창 제목과 프로세스 이름을 분석하여 공부/오락 판단
    
    - **window_title**: 분석할 창 제목
    - **process_name**: 프로세스 이름 (선택사항, 게임 감지용)
    - 반환: verdict (STUDY/DISTRACTION), reason, confidence
    """
    try:
        result = judge_window_title(request.window_title, request.process_name)
        return JudgeResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"판단 중 오류 발생: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))  # 기본 포트 8080
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

