
import asyncio
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.db.mongodb import init_db
from app.services.scheduler import midnight_detail_scheduler
from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(title="AI Chat Service", version="1.0.0")

# CORS Settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Development environment: allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    """Initialize database and start scheduler on app startup"""
    try:
        await init_db()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"⚠️ Database initialization error (startup): {e}")
    
    # Start midnight detail generation scheduler
    asyncio.create_task(midnight_detail_scheduler())
    print("✅ Scheduler task created")

@app.get("/")
def read_root():
    return {"service": "ai-chat-service", "status": "running"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# Include API Router containing all V1 endpoints
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
