#!/bin/bash

# 로컬 Kubernetes 배포 스크립트 (빌드 없이 배포만)
set -e

echo "🚀 Deploying to local Kubernetes..."

# 컨텍스트 확인
CONTEXT=$(kubectl config current-context 2>/dev/null || echo "")
if [ -z "$CONTEXT" ]; then
    echo "❌ Kubernetes 클러스터에 연결할 수 없습니다."
        exit 1
    fi

echo "📋 현재 컨텍스트: $CONTEXT"

# Namespace 생성
echo "📦 Creating namespace..."
kubectl create namespace jiaa-backend --dry-run=client -o yaml | kubectl apply -f -

# Secrets 확인
if ! kubectl get secret aws-credentials -n jiaa-backend &>/dev/null; then
    echo "⚠️  aws-credentials Secret이 없습니다. 기본값으로 생성합니다..."
    kubectl create secret generic aws-credentials \
        --from-literal=AWS_ACCESS_KEY_ID=dummy \
        --from-literal=AWS_SECRET_ACCESS_KEY=dummy \
        -n jiaa-backend \
        --dry-run=client -o yaml | kubectl apply -f -
fi

# Kustomize로 배포
echo ""
echo "📦 Applying Kustomize..."
kubectl apply -k k8s/local/

# 모든 서비스 대기
echo ""
echo "⏳ Waiting for all services to be ready..."
kubectl wait --for=condition=available \
    deployment/jiaa-ai-chat-service \
    deployment/jiaa-ai-judge-service \
    -n jiaa-backend \
    --timeout=300s || true

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
