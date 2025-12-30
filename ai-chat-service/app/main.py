
import asyncio
import os
import socket
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from py_eureka_client import eureka_client
from app.db.mongodb import init_db
from app.services.scheduler import midnight_detail_scheduler
from app.api.v1.router import api_router
from app.core.config import settings

# Gateway를 통한 접근을 위한 서버 URL 설정
servers = []
gateway_url = os.getenv("GATEWAY_URL", "http://localhost:8080")
if gateway_url:
    servers.append({"url": gateway_url, "description": "Gateway Server"})
servers.append({"url": "http://localhost:8080", "description": "Direct Access"})

app = FastAPI(
    title="AI Chat Service",
    version="1.0.0",
    servers=servers
)

# CORS Settings
# Gateway를 통해 접근할 때는 Gateway에서 CORS를 처리하므로
# FastAPI의 CORS 미들웨어는 비활성화 (중복 헤더 방지)
# WebSocket은 Gateway를 통해 접근하므로 Gateway의 CORS 설정이 적용됨
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],  # Development environment: allow all
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

@app.on_event("startup")
async def startup_event():
    """Initialize database, start scheduler, and register with Eureka"""
    try:
        await init_db()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️ Database initialization error (startup): {e}")
    
    # Start midnight detail generation scheduler
    asyncio.create_task(midnight_detail_scheduler())
    print("✅ Scheduler task created")
    
    # Register with Eureka
    try:
        eureka_server = os.getenv("EUREKA_SERVER", "http://discovery-service:8761/eureka")
        app_name = os.getenv("EUREKA_APP_NAME", "ai-chat-service")
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

@app.get("/")
def read_root():
    return {"service": "ai-chat-service", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Include API Router - Gateway handles /api/ prefix via rewritePath
app.include_router(api_router)

@app.on_event("shutdown")
async def shutdown_event():
    """Deregister from Eureka on shutdown"""
    try:
        await eureka_client.stop_async()
        print("✅ Deregistered from Eureka")
    except Exception as e:
        print(f"⚠️ Eureka deregistration error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True)
