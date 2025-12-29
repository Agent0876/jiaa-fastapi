#!/bin/bash

# Kaniko용 ECR 인증 Secret 생성 스크립트

set -e

REGION=${AWS_REGION:-ap-northeast-2}
ECR_REGISTRY=${ECR_REGISTRY:-541673202749.dkr.ecr.ap-northeast-2.amazonaws.com}
NAMESPACE=${NAMESPACE:-jiaa-backend}
SECRET_NAME=${SECRET_NAME:-kaniko-docker-config}

echo "🔐 Creating Kaniko ECR secret..."

# ECR 로그인
echo "Logging into ECR..."
aws ecr get-login-password --region ${REGION} | \
    docker login --username AWS --password-stdin ${ECR_REGISTRY}

# Docker config를 base64로 인코딩
DOCKER_CONFIG_B64=$(cat ~/.docker/config.json | base64 -w 0 2>/dev/null || cat ~/.docker/config.json | base64)

# Secret 생성
kubectl create secret generic ${SECRET_NAME} \
    --from-literal=.dockerconfigjson=$(echo ${DOCKER_CONFIG_B64} | base64 -d | jq -c .) \
    --type=kubernetes.io/dockerconfigjson \
    -n ${NAMESPACE} \
    --dry-run=client -o yaml | kubectl apply -f -

echo "✅ Secret created: ${SECRET_NAME} in namespace ${NAMESPACE}"

