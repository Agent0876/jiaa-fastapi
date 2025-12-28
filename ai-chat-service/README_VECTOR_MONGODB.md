# MongoDB Atlas Vector Search 가이드

이 서비스는 MongoDB Atlas Vector Search를 사용하여 벡터 검색을 수행합니다.

## 벡터 검색 방식

1. **MongoDB Atlas Vector Search** (우선): Atlas에서 벡터 인덱스를 사용한 고성능 검색
2. **애플리케이션 레벨 검색** (폴백): Atlas가 없거나 인덱스가 없는 경우 코사인 유사도로 검색

## MongoDB Atlas Vector Search 설정

### 1. Atlas UI에서 벡터 인덱스 생성

1. [MongoDB Atlas 콘솔](https://cloud.mongodb.com) 접속
2. 프로젝트 선택 > Database > Browse Collections
3. `conversation_messages` 컬렉션 선택
4. **Indexes** 탭 클릭
5. **Create Search Index** 버튼 클릭
6. **JSON Editor** 선택
7. 아래 JSON을 입력:

```json
{
  "name": "vector_index",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      {
        "type": "vector",
        "path": "embedding",
        "numDimensions": 768,
        "similarity": "cosine"
      }
    ]
  }
}
```

8. **Next** > **Create Search Index** 클릭
9. 인덱스 생성 완료까지 몇 분 소요될 수 있습니다.

### 2. 환경 변수 설정

```bash
# 벡터 인덱스 이름 (기본값: "vector_index")
export MONGO_VECTOR_INDEX_NAME=vector_index

# MongoDB 연결 정보
export MONGO_HOST=your-cluster.mongodb.net
export MONGO_PORT=27017
export MONGO_DB_NAME=jiwon
export MONGO_USER=your-username
export MONGO_PASSWORD=your-password
```

### 3. 로컬 MongoDB 6.0.11+ 사용 시

MongoDB 6.0.11 이상 버전을 사용하는 경우, 로컬에서도 벡터 검색을 사용할 수 있습니다:

```bash
# MongoDB 6.0.11+ Docker 실행
docker run -d \
  --name mongodb-vector \
  -p 27017:27017 \
  -e MONGO_INITDB_DATABASE=jiwon \
  mongo:6.0.11
```

인덱스 생성:
```bash
python create_vector_index.py
```

## 벡터 검색 작동 방식

### Atlas Vector Search 사용 시

```python
# $vectorSearch aggregation pipeline 사용
pipeline = [
    {
        "$vectorSearch": {
            "index": "vector_index",
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": 50,
            "limit": 5
        }
    },
    {
        "$addFields": {
            "similarity": {"$meta": "vectorSearchScore"}
        }
    }
]
```

### 폴백 (애플리케이션 레벨)

Atlas Vector Search가 사용 불가능한 경우:
- 모든 메시지를 가져와서 애플리케이션에서 코사인 유사도 계산
- 유사도 순으로 정렬하여 상위 N개 반환

## 임베딩 차원

현재 사용 중인 임베딩 모델: `jhgan/ko-sroberta-multitask`
- 차원: **768**
- 환경 변수로 변경 가능: `EMBEDDING_DIMENSION=768`

다른 모델을 사용하는 경우:
1. `EMBEDDING_DIMENSION` 환경 변수 설정
2. Atlas 인덱스의 `numDimensions` 값 변경

## 성능 비교

| 방식 | 속도 | 정확도 | 메모리 사용 |
|------|------|--------|------------|
| Atlas Vector Search | 매우 빠름 | 높음 | 낮음 |
| 애플리케이션 레벨 | 느림 (데이터 많을수록) | 높음 | 높음 |

**권장**: 프로덕션에서는 MongoDB Atlas Vector Search 사용을 강력히 권장합니다.

## 문제 해결

### 벡터 검색이 작동하지 않는 경우

1. **인덱스 확인**
   ```bash
   # Atlas 콘솔에서 인덱스 상태 확인
   # Status가 "Active"인지 확인
   ```

2. **인덱스 이름 확인**
   ```bash
   # 환경 변수 MONGO_VECTOR_INDEX_NAME이 올바른지 확인
   echo $MONGO_VECTOR_INDEX_NAME
   ```

3. **로그 확인**
   ```
   ⚠️ MongoDB Atlas Vector Search 실패, 폴백 사용: ...
   ```
   위 메시지가 나타나면 폴백 모드로 작동 중입니다.

4. **MongoDB 버전 확인**
   - Atlas: 모든 버전 지원
   - 로컬: MongoDB 6.0.11+ 필요

## 참고 자료

- [MongoDB Atlas Vector Search 문서](https://www.mongodb.com/docs/atlas/atlas-vector-search/)
- [MongoDB Vector Search 가이드](https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-overview/)

