#!/bin/bash

# 로컬에서 Python 서비스를 빌드하고 Kubernetes에 배포하는 통합 스크립트

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 옵션 파싱
BUILD_ONLY=false
DEPLOY_ONLY=false
SERVICE_NAME=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --build-only)
            BUILD_ONLY=true
            shift
            ;;
        --deploy-only)
            DEPLOY_ONLY=true
            shift
            ;;
        --service)
            SERVICE_NAME="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "🚀 Local Kubernetes Deployment Script"
echo "======================================"

# Kubernetes 컨텍스트 확인
CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")
if [ -z "$CONTEXT" ]; then
    echo "❌ Kubernetes 클러스터에 연결할 수 없습니다."
    echo "   Docker Desktop, minikube, 또는 kind를 실행 중인지 확인하세요."
    exit 1
fi

echo "📋 현재 Kubernetes 컨텍스트: $CONTEXT"

# 로컬 Kubernetes 환경 감지
if [[ "$CONTEXT" == *"docker-desktop"* ]] || [[ "$CONTEXT" == *"minikube"* ]] || [[ "$CONTEXT" == *"kind"* ]]; then
    echo "✅ 로컬 Kubernetes 환경 감지됨"
else
    echo "⚠️  경고: 프로덕션 클러스터일 수 있습니다. 계속하시겠습니까? (y/n)"
    read -r answer
    if [[ "$answer" != "y" ]]; then
        exit 1
    fi
fi

# 1. Docker 이미지 빌드
if [ "$DEPLOY_ONLY" = false ]; then
    echo ""
    echo "🔨 Step 1: Building Docker images..."
    cd "$ROOT_DIR"
    
    if [ -n "$SERVICE_NAME" ]; then
        echo "   Building only: $SERVICE_NAME"
        SERVICES=("$SERVICE_NAME")
    else
        SERVICES=("ai-chat-service" "ai-judge-service")
    fi
    
    for SERVICE in "${SERVICES[@]}"; do
        echo ""
        echo "📦 Building $SERVICE..."
        
        SERVICE_DIR="./${SERVICE}"
        if [ ! -d "$SERVICE_DIR" ]; then
            echo "❌ 서비스 디렉토리를 찾을 수 없습니다: $SERVICE_DIR"
            exit 1
        fi
        
        if [ ! -f "$SERVICE_DIR/Dockerfile" ]; then
            echo "❌ Dockerfile을 찾을 수 없습니다: $SERVICE_DIR/Dockerfile"
            exit 1
        fi
        
        IMAGE_NAME="jiaa-${SERVICE}:local"
        docker build -t "$IMAGE_NAME" -f "$SERVICE_DIR/Dockerfile" "$SERVICE_DIR"
        echo "   ✅ Built: $IMAGE_NAME"
    done
    
    # minikube 환경인 경우 이미지를 minikube에 로드
    if [[ "$CONTEXT" == *"minikube"* ]]; then
        echo ""
        echo "📥 Loading images into minikube..."
        for SERVICE in "${SERVICES[@]}"; do
            IMAGE_NAME="jiaa-${SERVICE}:local"
            minikube image load "$IMAGE_NAME" || true
        done
    fi
fi

# 2. Kubernetes 배포
if [ "$BUILD_ONLY" = false ]; then
    echo ""
    echo "🚀 Step 2: Deploying to Kubernetes..."
    cd "$ROOT_DIR"
    
    # Namespace 생성
    echo "   Creating namespace..."
    kubectl create namespace jiaa-backend --dry-run=client -o yaml | kubectl apply -f -
    
    # Secrets 생성 (없는 경우)
    if [ ! -f "k8s/local/secrets-local.yaml" ]; then
        echo "   ⚠️  secrets-local.yaml이 없습니다. 기본 Secret을 생성합니다..."
        kubectl create secret generic aws-credentials \
            --from-literal=AWS_ACCESS_KEY_ID=dummy \
            --from-literal=AWS_SECRET_ACCESS_KEY=dummy \
            -n jiaa-backend \
            --dry-run=client -o yaml | kubectl apply -f - || true
    fi
    
    # Kustomize로 배포
    echo "   Applying Kustomize..."
    kubectl apply -k k8s/local/
    
    # 배포 대기
    echo ""
    echo "⏳ Waiting for deployments to be ready..."
    
    if [ -n "$SERVICE_NAME" ]; then
        DEPLOYMENTS=("jiaa-${SERVICE_NAME}")
    else
        DEPLOYMENTS=("jiaa-ai-chat-service" "jiaa-ai-judge-service")
    fi
    
    for DEPLOYMENT in "${DEPLOYMENTS[@]}"; do
        echo "   Waiting for $DEPLOYMENT..."
        kubectl wait --for=condition=available \
            --timeout=300s \
            deployment/$DEPLOYMENT \
            -n jiaa-backend || {
            echo "   ⚠️  $DEPLOYMENT 배포 실패 또는 타임아웃"
            kubectl describe deployment/$DEPLOYMENT -n jiaa-backend || true
        }
    done
    
    echo ""
    echo "✅ Deployment complete!"
    echo ""
    echo "📋 Pod status:"
    kubectl get pods -n jiaa-backend
    echo ""
    echo "🌐 Service status:"
    kubectl get svc -n jiaa-backend
    echo ""
    echo "💡 Port forwarding:"
    echo "   ./scripts/port-forward.sh"
fi

echo ""
echo "✨ Done!"

