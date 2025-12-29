#!/bin/bash

# 로컬 Docker 이미지 빌드 스크립트
# Kaniko 사용 옵션 제공

set -e

USE_KANIKO=${USE_KANIKO:-false}
BUILD_NUMBER=${BUILD_NUMBER:-local}

echo "🔨 Building all services for local Kubernetes..."

if [ "$USE_KANIKO" = "true" ]; then
    echo "🚀 Using Kaniko for building..."
    for SERVICE in ai-chat-service ai-judge-service; do
        echo "📦 Building $SERVICE with Kaniko..."
        ./scripts/build-with-kaniko.sh "$SERVICE" "$BUILD_NUMBER" || {
            echo "⚠️  Kaniko build failed for $SERVICE, falling back to Docker..."
            USE_KANIKO=false
        }
    done
fi

if [ "$USE_KANIKO" != "true" ]; then
    echo "🐳 Building Docker images locally..."
    
    SERVICES=("ai-chat-service" "ai-judge-service")

for SERVICE in "${SERVICES[@]}"; do
    echo ""
    echo "📦 Building $SERVICE image..."
    
    # 서비스 디렉토리 확인
    SERVICE_DIR="./${SERVICE}"
    if [ ! -d "$SERVICE_DIR" ]; then
        echo "❌ 서비스 디렉토리를 찾을 수 없습니다: $SERVICE_DIR"
        exit 1
    fi
    
    # Dockerfile 확인
    if [ ! -f "$SERVICE_DIR/Dockerfile" ]; then
        echo "❌ Dockerfile을 찾을 수 없습니다: $SERVICE_DIR/Dockerfile"
        exit 1
    fi
    
    # Docker 이미지 빌드
    IMAGE_NAME="jiaa-${SERVICE}:local"
    docker build -t "$IMAGE_NAME" -f "$SERVICE_DIR/Dockerfile" "$SERVICE_DIR"
done

echo ""
echo "✅ All images built successfully!"
echo ""
echo "Built images:"
docker images | grep "jiaa-.*:local"
fi
