
from pymongo import MongoClient
from langchain_aws import BedrockEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from app.core.config import settings
import boto3

# AWS Bedrock 클라이언트 초기화
bedrock_client = boto3.client(
    service_name="bedrock-runtime",
    region_name=settings.AWS_REGION,
    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
)

# LangChain Bedrock 임베딩 초기화
embeddings = None
try:
    embeddings = BedrockEmbeddings(
        client=bedrock_client,
        model_id=settings.EMBEDDING_MODEL_ID,
    )
    print(f"✅ LangChain Bedrock 임베딩 모델 로드 완료: {settings.EMBEDDING_MODEL_ID}")
except Exception as e:
    print(f"⚠️ 임베딩 모델 로드 실패: {e}")
    embeddings = None

# LangChain Vector Store 초기화 (conversation_messages 컬렉션 사용)
vector_store = None
try:
    if embeddings:
        # Vector Store는 동기 MongoClient 사용 (LangChain 호환성)
        mongo_client = MongoClient(settings.MONGO_URI)
        collection = mongo_client[settings.MONGO_DB_NAME]["conversation_messages"]
        
        vector_store = MongoDBAtlasVectorSearch(
            collection=collection,
            embedding=embeddings,
            index_name=settings.VECTOR_INDEX_NAME,
            text_key="content",
            embedding_key="embedding"
        )
        print(f"✅ LangChain MongoDB Vector Store 초기화 완료: conversation_messages 컬렉션")
except Exception as e:
    print(f"⚠️ LangChain Vector Store 초기화 실패: {e}")
    vector_store = None
