# Kaniko 빌드 가이드

## 개요

Kaniko는 Kubernetes 클러스터 내에서 Docker 이미지를 빌드하는 도구입니다. Docker-in-Docker 없이도 작동하며, 보안이 강화된 빌드 환경을 제공합니다.

## 사전 준비

### 1. Kubernetes 클러스터 접근
```bash
kubectl cluster-info
```

### 2. ServiceAccount 및 RBAC 설정
```bash
kubectl apply -f k8s/kaniko-serviceaccount.yaml
```

### 3. ECR 인증 Secret 생성
```bash
cd jiaa-fastapi
./scripts/create-kaniko-secret.sh
```

또는 수동으로:
```bash
# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 | \
    docker login --username AWS --password-stdin 541673202749.dkr.ecr.ap-northeast-2.amazonaws.com

# Secret 생성
kubectl create secret generic kaniko-docker-config \
    --from-file=.dockerconfigjson=$HOME/.docker/config.json \
    --type=kubernetes.io/dockerconfigjson \
    -n jiaa-backend
```

## 사용 방법

### 방법 1: 스크립트 사용
```bash
cd jiaa-fastapi

# 단일 서비스 빌드
./scripts/build-with-kaniko.sh ai-judge-service 123

# 모든 서비스 빌드 (로컬 Docker 사용)
./scripts/build-local.sh

# Kaniko 사용
USE_KANIKO=true ./scripts/build-local.sh
```

### 방법 2: Jenkins 파이프라인
```groovy
// Jenkinsfile.kaniko 사용
pipeline {
    agent any
    stages {
        stage('Build') {
            steps {
                sh './jiaa-fastapi/scripts/build-with-kaniko.sh ai-judge-service ${BUILD_NUMBER}'
            }
        }
    }
}
```

### 방법 3: Kubernetes Job 직접 실행
```bash
# Job YAML 수정 (BUILD_NUMBER 등)
kubectl apply -f k8s/kaniko-build-job.yaml

# 로그 확인
kubectl logs -f job/kaniko-build-ai-judge-service-1 -n jiaa-backend

# 상태 확인
kubectl get job -n jiaa-backend
```

## 빌드 프로세스

1. **Job 생성**: Kubernetes에 Kaniko Job 생성
2. **컨텍스트 복사**: 소스 코드를 Pod에 마운트
3. **이미지 빌드**: Kaniko가 Dockerfile을 읽어 이미지 빌드
4. **ECR 푸시**: 빌드된 이미지를 ECR에 푸시
5. **Job 완료**: TTL에 따라 자동 삭제

## 장점

- ✅ Docker-in-Docker 불필요
- ✅ 보안 강화 (루트 권한 불필요)
- ✅ Kubernetes 네이티브
- ✅ 캐싱 지원 (빌드 속도 향상)

## 주의사항

- Kaniko는 Linux 기반 이미지만 빌드 가능
- Electron 네이티브 모니터(macOS/Windows)는 여전히 각 플랫폼에서 빌드 필요
- ECR 인증이 올바르게 설정되어 있어야 함

## 트러블슈팅

### Secret이 없을 때
```bash
kubectl get secret kaniko-docker-config -n jiaa-backend
# 없으면 create-kaniko-secret.sh 실행
```

### 권한 오류
```bash
kubectl auth can-i create jobs --namespace=jiaa-backend --as=system:serviceaccount:jiaa-backend:kaniko-sa
# ServiceAccount 권한 확인
```

### 빌드 실패
```bash
# Job 로그 확인
kubectl logs job/kaniko-build-ai-judge-service-1 -n jiaa-backend

# Pod 이벤트 확인
kubectl describe job/kaniko-build-ai-judge-service-1 -n jiaa-backend
```

