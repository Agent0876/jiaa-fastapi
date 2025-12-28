# Docker MongoDB 벡터 검색 설정 가이드

이 가이드에서는 Docker로 MongoDB를 실행하고 벡터 검색을 설정하는 방법을 설명합니다.

## 요구사항

- **MongoDB 6.0.11 이상**: 벡터 검색 기능 지원
- Docker 설치 및 실행 중

## 빠른 시작

### 1. MongoDB Docker 실행

```bash
# 스크립트 사용 (권장)
./docker-mongodb.sh

# 또는 직접 실행
docker run -d \
  --name mongodb-vector \
  -p 27017:27017 \
  -v mongodb-vector-data:/data/db \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:6.0.11
```

### 2. 벡터 인덱스 생성

```bash
# 환경 변수 설정 (필요한 경우)
export MONGO_HOST=localhost
export MONGO_PORT=27017
export MONGO_DB_NAME=jiwon
# 인증이 필요한 경우
# export MONGO_USER=admin
# export MONGO_PASSWORD=yourpassword

# 벡터 인덱스 생성
python create_vector_index.py
```

### 3. 애플리케이션 실행

```bash
# 환경 변수 설정
export MONGO_HOST=localhost
export MONGO_PORT=27017
export MONGO_DB_NAME=jiwon
export MONGO_VECTOR_INDEX_NAME=vector_index

# 애플리케이션 실행
uvicorn main:app --reload
```

## 상세 설정

### MongoDB 버전 선택

#### MongoDB 6.0.11+ (벡터 검색 지원) - 권장

```bash
docker run -d \
  --name mongodb-vector \
  -p 27017:27017 \
  -v mongodb-vector-data:/data/db \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:6.0.11
```

#### MongoDB 5.0 (DocumentDB 호환, 벡터 검색 미지원)

```bash
docker run -d \
  --name mongodb-documentdb \
  -p 27017:27017 \
  -v mongodb-data:/data/db \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:5.0
```

**주의**: MongoDB 5.0에서는 벡터 검색이 지원되지 않으므로, 애플리케이션 레벨 검색(폴백)만 사용됩니다.

### 인증 포함 실행

```bash
docker run -d \
  --name mongodb-vector \
  -p 27017:27017 \
  -v mongodb-vector-data:/data/db \
  -e MONGO_INITDB_ROOT_USERNAME=admin \
  -e MONGO_INITDB_ROOT_PASSWORD=yourpassword \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:6.0.11
```

환경 변수 설정:
```bash
export MONGO_USER=admin
export MONGO_PASSWORD=yourpassword
```

### Docker Compose 사용

`docker-compose.yml`:

```yaml
version: '3.8'

services:
  mongodb:
    image: mongo:6.0.11
    container_name: mongodb-vector
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_DATABASE: jiwon
      # 인증이 필요한 경우
      # MONGO_INITDB_ROOT_USERNAME: admin
      # MONGO_INITDB_ROOT_PASSWORD: yourpassword
    volumes:
      - mongodb-vector-data:/data/db
    restart: unless-stopped

volumes:
  mongodb-vector-data:
```

실행:
```bash
docker-compose up -d
```

## 벡터 검색 작동 확인

### 1. 인덱스 생성 확인

```bash
# MongoDB 쉘 접속
docker exec -it mongodb-vector mongosh

# 인덱스 확인
use jiwon
db.conversation_messages.getSearchIndexes()
```

### 2. 애플리케이션 로그 확인

벡터 검색이 작동하는 경우:
```
✅ MongoDB Atlas Vector Search 사용: 5개 결과
```

폴백 모드인 경우:
```
⚠️ MongoDB Atlas Vector Search 실패, 폴백 사용: ...
ℹ️ 애플리케이션 레벨 벡터 검색 사용 (폴백)
```

## 유용한 명령어

```bash
# 컨테이너 상태 확인
docker ps | grep mongodb-vector

# 로그 확인
docker logs mongodb-vector
docker logs -f mongodb-vector  # 실시간 로그

# 컨테이너 중지
docker stop mongodb-vector

# 컨테이너 시작
docker start mongodb-vector

# 컨테이너 삭제 (데이터는 볼륨에 보존됨)
docker rm -f mongodb-vector

# 볼륨 삭제 (데이터 삭제)
docker volume rm mongodb-vector-data

# MongoDB 쉘 접속
docker exec -it mongodb-vector mongosh

# 데이터베이스 확인
docker exec -it mongodb-vector mongosh --eval "show dbs"

# 컬렉션 확인
docker exec -it mongodb-vector mongosh jiwon --eval "show collections"
```

## 문제 해결

### 벡터 검색이 작동하지 않는 경우

1. **MongoDB 버전 확인**
   ```bash
   docker exec -it mongodb-vector mongosh --eval "db.version()"
   ```
   - 6.0.11 이상이어야 합니다.

2. **인덱스 확인**
   ```bash
   docker exec -it mongodb-vector mongosh jiwon --eval "db.conversation_messages.getSearchIndexes()"
   ```
   - `vector_index`가 있어야 합니다.

3. **인덱스 재생성**
   ```bash
   # 기존 인덱스 삭제 후 재생성
   docker exec -it mongodb-vector mongosh jiwon --eval "db.conversation_messages.dropSearchIndex('vector_index')"
   python create_vector_index.py
   ```

### 연결 오류

```bash
# 컨테이너가 실행 중인지 확인
docker ps | grep mongodb-vector

# 포트가 사용 중인지 확인
lsof -i :27017

# 다른 프로세스가 포트를 사용 중이면 중지
```

### 인증 오류

```bash
# 환경 변수 확인
echo $MONGO_USER
echo $MONGO_PASSWORD

# MongoDB 쉘로 직접 연결 테스트
docker exec -it mongodb-vector mongosh -u admin -p yourpassword
```

## 성능 최적화

### 벡터 검색 vs 폴백

| 방식 | 속도 | 메모리 | 데이터량 제한 |
|------|------|--------|--------------|
| 벡터 검색 (6.0.11+) | 매우 빠름 | 낮음 | 제한 없음 |
| 폴백 (5.0) | 느림 | 높음 | 수천 개 이상 시 느림 |

**권장**: 프로덕션에서는 MongoDB 6.0.11+ 사용을 강력히 권장합니다.

## 참고 자료

- [MongoDB 6.0 벡터 검색 문서](https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-overview/)
- [MongoDB Docker Hub](https://hub.docker.com/_/mongo)

