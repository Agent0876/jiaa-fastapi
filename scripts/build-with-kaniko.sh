#!/bin/bash

# Kaniko를 사용한 Docker 이미지 빌드 스크립트

set -e

SERVICE_NAME=${1:-ai-judge-service}
BUILD_NUMBER=${2:-$(date +%s)}
ECR_REGISTRY=${ECR_REGISTRY:-541673202749.dkr.ecr.ap-northeast-2.amazonaws.com}
AWS_REGION=${AWS_REGION:-ap-northeast-2}
K8S_NAMESPACE=${K8S_NAMESPACE:-jiaa-backend}
KANIKO_SA=${KANIKO_SA:-kaniko-sa}

echo "🔨 Building ${SERVICE_NAME} with Kaniko..."

# Dockerfile 경로 확인
DOCKERFILE="jiaa-fastapi/${SERVICE_NAME}/Dockerfile"
if [ ! -f "$DOCKERFILE" ]; then
    echo "❌ Dockerfile not found: $DOCKERFILE"
    exit 1
fi

# Kaniko Job 생성
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: kaniko-build-${SERVICE_NAME}-${BUILD_NUMBER}
  namespace: ${K8S_NAMESPACE}
spec:
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      serviceAccountName: ${KANIKO_SA}
      containers:
      - name: kaniko
        image: gcr.io/kaniko-project/executor:latest
        args:
        - --dockerfile=${DOCKERFILE}
        - --context=dir:///workspace
        - --destination=${ECR_REGISTRY}/jiaa/${SERVICE_NAME}:${BUILD_NUMBER}
        - --destination=${ECR_REGISTRY}/jiaa/${SERVICE_NAME}:latest
        - --cache=true
        - --cache-ttl=24h
        - --snapshot-mode=redo
        - --verbosity=info
        env:
        - name: AWS_REGION
          value: "${AWS_REGION}"
        volumeMounts:
        - name: kaniko-secret
          mountPath: /kaniko/.docker
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
      restartPolicy: Never
      volumes:
      - name: kaniko-secret
        secret:
          secretName: kaniko-docker-config
EOF

echo "⏳ Waiting for Kaniko build to complete..."

# Job 완료 대기 (최대 10분)
kubectl wait --for=condition=complete \
    --timeout=600s \
    job/kaniko-build-${SERVICE_NAME}-${BUILD_NUMBER} \
    -n ${K8S_NAMESPACE} || {
    echo "❌ Build failed or timeout"
    kubectl logs job/kaniko-build-${SERVICE_NAME}-${BUILD_NUMBER} -n ${K8S_NAMESPACE} || true
    exit 1
}

echo "✅ Build completed successfully!"
echo "📦 Image: ${ECR_REGISTRY}/jiaa/${SERVICE_NAME}:${BUILD_NUMBER}"

