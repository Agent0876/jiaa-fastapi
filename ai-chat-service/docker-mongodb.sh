#!/bin/bash

# MongoDB 6.0.11+ Docker 실행 스크립트 (벡터 검색 지원)

echo "🚀 MongoDB 6.0.11+ Docker 컨테이너 실행 중..."

# 기존 컨테이너가 있으면 중지 및 삭제
if [ "$(docker ps -aq -f name=mongodb-vector)" ]; then
    echo "📦 기존 컨테이너 중지 및 삭제 중..."
    docker stop mongodb-vector
    docker rm mongodb-vector
fi

# MongoDB 6.0.11+ 실행 (벡터 검색 지원)
docker run -d \
  --name mongodb-vector \
  -p 27017:27017 \
  -v mongodb-vector-data:/data/db \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:6.0.11

echo "✅ MongoDB 6.0.11+ 컨테이너가 실행되었습니다!"
echo ""
echo "📋 다음 단계:"
echo "1. 컨테이너가 완전히 시작될 때까지 몇 초 대기"
echo "2. 벡터 인덱스 생성: python create_vector_index.py"
echo ""
echo "🔍 컨테이너 상태 확인:"
echo "   docker ps | grep mongodb-vector"
echo ""
echo "📝 로그 확인:"
echo "   docker logs mongodb-vector"

