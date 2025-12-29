#!/bin/bash

set -e

# AWS 자격 증명 Secret 생성 스크립트

NAMESPACE=${1:-jiaa-backend}
SECRET_NAME="aws-credentials"

echo "🔐 AWS 자격 증명 Secret 생성 스크립트"
echo "   네임스페이스: $NAMESPACE"
echo "   Secret 이름: $SECRET_NAME"
echo ""

# 네임스페이스 확인/생성
if ! kubectl get namespace "$NAMESPACE" &>/dev/null; then
    echo "📦 네임스페이스 생성 중: $NAMESPACE"
    kubectl create namespace "$NAMESPACE"
fi

# 기존 Secret 확인
if kubectl get secret "$SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
    echo "⚠️  Secret이 이미 존재합니다: $SECRET_NAME"
    read -p "덮어쓰시겠습니까? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "취소되었습니다."
        exit 1
    fi
    kubectl delete secret "$SECRET_NAME" -n "$NAMESPACE"
fi

# 환경 변수에서 값 읽기 또는 입력 받기
if [ -z "$AWS_ACCESS_KEY_ID" ]; then
    read -sp "AWS Access Key ID를 입력하세요: " AWS_ACCESS_KEY_ID
    echo
fi

if [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    read -sp "AWS Secret Access Key를 입력하세요: " AWS_SECRET_ACCESS_KEY
    echo
fi

AWS_REGION=${AWS_REGION:-us-east-1}

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "❌ AWS 자격 증명이 제공되지 않았습니다."
    exit 1
fi

# Secret 생성
echo "🔑 Secret 생성 중..."
kubectl create secret generic "$SECRET_NAME" \
    --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID" \
    --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY" \
    --from-literal=AWS_REGION="$AWS_REGION" \
    -n "$NAMESPACE"

echo ""
echo "✅ Secret 생성 완료!"
echo "   확인: kubectl get secret $SECRET_NAME -n $NAMESPACE"
echo "   내용 확인: kubectl describe secret $SECRET_NAME -n $NAMESPACE"

