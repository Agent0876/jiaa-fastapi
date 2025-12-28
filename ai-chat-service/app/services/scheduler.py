
import asyncio
from datetime import datetime, timedelta
import pytz

from app.db.mongodb import get_collection
from app.services.roadmap import generate_day_details

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


async def midnight_detail_scheduler():
    """매일 자정(KST)에 오늘 일차의 상세 내용 생성"""
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
