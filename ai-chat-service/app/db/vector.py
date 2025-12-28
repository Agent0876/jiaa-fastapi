
from pymongo import MongoClient
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from app.core.config import settings

# LangChain HuggingFace 임베딩 초기화
embeddings = None
try:
    embeddings = HuggingFaceEmbeddings(
        model_name=settings.EMBEDDING_MODEL_NAME,
        model_kwargs={'device': 'cpu'},  # GPU가 있으면 'cuda'로 변경 가능
        encode_kwargs={'normalize_embeddings': True}  # 정규화하여 코사인 유사도 최적화
    )
    print(f"✅ LangChain 임베딩 모델 로드 완료: {settings.EMBEDDING_MODEL_NAME}")
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
