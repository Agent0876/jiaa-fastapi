# 로컬 Kubernetes 배포 가이드

로컬에서 Python 서비스를 빌드하고 Kubernetes에 배포하는 방법입니다.

## 사전 준비

### 1. Kubernetes 클러스터 준비

다음 중 하나를 실행 중이어야 합니다:

#### Docker Desktop (가장 간단)
```bash
# Docker Desktop 실행 후 Kubernetes 활성화
# Settings > Kubernetes > Enable Kubernetes
```

#### minikube
```bash
minikube start
kubectl config use-context minikube
```

#### kind (Kubernetes in Docker)
```bash
kind create cluster --name jiwon-tech
kubectl config use-context kind-jiwon-tech
```

### 2. kubectl 설치 확인
```bash
kubectl version --client
kubectl cluster-info
```

## 빠른 시작

### 전체 서비스 빌드 및 배포
```bash
cd jiaa-fastapi
./scripts/deploy-local-all.sh
```

### 특정 서비스만 배포
```bash
./scripts/deploy-local-all.sh --service ai-judge-service
```

### 빌드만 (배포 안 함)
```bash
./scripts/deploy-local-all.sh --build-only
```

### 배포만 (빌드 안 함)
```bash
./scripts/deploy-local-all.sh --deploy-only
```

## 단계별 가이드

### 1. Docker 이미지 빌드

```bash
cd jiaa-fastapi

# 모든 서비스 빌드
./scripts/build-local.sh

# 또는 개별 빌드
docker build -t jiaa-ai-judge-service:local \
    -f ai-judge-service/Dockerfile \
    ai-judge-service/
```

### 2. minikube 사용 시 이미지 로드

```bash
# minikube에 이미지 로드
minikube image load jiaa-ai-judge-service:local
minikube image load jiaa-ai-chat-service:local
```

**참고**: Docker Desktop은 로컬 이미지를 자동으로 사용하므로 별도 로드 불필요

### 3. Kubernetes 배포

```bash
# Kustomize로 배포
kubectl apply -k k8s/local/

# 또는 개별 배포
kubectl apply -f k8s/local/ai-judge-service.yaml
```

### 4. 배포 상태 확인

```bash
# Pod 상태 확인
kubectl get pods -n jiaa-backend

# Pod 로그 확인
kubectl logs -f deployment/jiaa-ai-judge-service -n jiaa-backend

# Service 확인
kubectl get svc -n jiaa-backend
```

### 5. Port Forwarding (로컬 접근)

```bash
# 모든 서비스 포트 포워딩
./scripts/port-forward.sh

# 또는 개별 포트 포워딩
kubectl port-forward svc/jiaa-ai-judge-service-svc 8002:8002 -n jiaa-backend
```

## 환경별 설정

### Docker Desktop
- 로컬 이미지 자동 사용 (`imagePullPolicy: Never`)
- 추가 설정 불필요

### minikube
```bash
# 이미지 로드 필요
minikube image load jiaa-ai-judge-service:local

# 또는 minikube의 Docker 데몬 사용
eval $(minikube docker-env)
docker build -t jiaa-ai-judge-service:local ...
```

### kind
```bash
# 이미지 로드 필요
kind load docker-image jiaa-ai-judge-service:local --name jiwon-tech
```

## Secrets 설정

로컬 개발용 AWS 자격증명 설정:

```bash
# secrets-local.yaml 파일 생성 또는
kubectl create secret generic aws-credentials \
    --from-literal=AWS_ACCESS_KEY_ID=your-key \
    --from-literal=AWS_SECRET_ACCESS_KEY=your-secret \
    -n jiaa-backend
```

## 트러블슈팅

### 이미지를 찾을 수 없음
```bash
# 이미지 확인
docker images | grep jiaa

# minikube 사용 시
minikube image ls

# 이미지 다시 로드
minikube image load jiaa-ai-judge-service:local
```

### Pod가 시작되지 않음
```bash
# Pod 이벤트 확인
kubectl describe pod <pod-name> -n jiaa-backend

# Pod 로그 확인
kubectl logs <pod-name> -n jiaa-backend
```

### 포트 포워딩 실패
```bash
# 기존 포트 포워딩 확인
kubectl get pods -n jiaa-backend | grep port-forward

# 포트 사용 중인지 확인
lsof -i :8002
```

### 네임스페이스가 없음
```bash
kubectl create namespace jiaa-backend
```

## 개발 워크플로우

### 1. 코드 수정 후 재배포
```bash
# 이미지 재빌드
docker build -t jiaa-ai-judge-service:local \
    -f ai-judge-service/Dockerfile \
    ai-judge-service/

# Deployment 재시작
kubectl rollout restart deployment/jiaa-ai-judge-service -n jiaa-backend
```

### 2. 로그 실시간 확인
```bash
kubectl logs -f deployment/jiaa-ai-judge-service -n jiaa-backend
```

### 3. 환경 변수 변경
```bash
# Deployment 수정
kubectl edit deployment/jiaa-ai-judge-service -n jiaa-backend

# 또는 ConfigMap/Secret 사용
kubectl apply -f k8s/local/secrets-local.yaml
kubectl rollout restart deployment/jiaa-ai-judge-service -n jiaa-backend
```

## 정리

### 모든 리소스 삭제
```bash
kubectl delete -k k8s/local/
```

### 특정 서비스만 삭제
```bash
kubectl delete deployment jiaa-ai-judge-service -n jiaa-backend
kubectl delete svc jiaa-ai-judge-service-svc -n jiaa-backend
```

### 네임스페이스 삭제
```bash
kubectl delete namespace jiaa-backend
```

## 유용한 명령어

```bash
# 모든 Pod 재시작
kubectl rollout restart deployment -n jiaa-backend

# Pod 쉘 접속
kubectl exec -it <pod-name> -n jiaa-backend -- /bin/sh

# Service 엔드포인트 확인
kubectl get endpoints -n jiaa-backend

# 리소스 사용량 확인
kubectl top pods -n jiaa-backend
```

