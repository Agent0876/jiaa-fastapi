import os
from typing import Optional

class Settings:
    # Load .env file manually if exists (to avoid adding python-dotenv dependency)
    try:
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        env_file = os.path.join(root_dir, ".env")
        if os.path.exists(env_file):
            print(f"Loading .env from {env_file}")
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    key, value = line.split("=", 1)
                    if key not in os.environ:
                        os.environ[key] = value
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")

    # API Settings
    API_V1_STR: str = ""  # Gateway handles /api/ prefix
    PROJECT_NAME: str = "AI Chat Service"
    USER_SERVICE_URL: str = os.getenv("USER_SERVICE_URL", "http://user-service:8080")
    
    # MongoDB
    MONGO_HOST: str = os.getenv("MONGO_HOST", "localhost")
    MONGO_PORT: int = int(os.getenv("MONGO_PORT", "27017"))
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "jiwon")
    MONGO_USER: str = os.getenv("MONGO_USER", "")
    MONGO_PASSWORD: str = os.getenv("MONGO_PASSWORD", "")
    VECTOR_INDEX_NAME: str = os.getenv("MONGO_VECTOR_INDEX_NAME", "vector_index")

    @property
    def MONGO_URI(self) -> str:
        """Constructs MongoDB URI based on available credentials."""
        if self.MONGO_USER and self.MONGO_PASSWORD:
            return f"mongodb://{self.MONGO_USER}:{self.MONGO_PASSWORD}@{self.MONGO_HOST}:{self.MONGO_PORT}/{self.MONGO_DB_NAME}?authSource=admin"
        return f"mongodb://{self.MONGO_HOST}:{self.MONGO_PORT}/{self.MONGO_DB_NAME}"

    # AWS & Bedrock
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    AWS_ACCESS_KEY_ID: Optional[str] = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY: Optional[str] = os.getenv("AWS_SECRET_ACCESS_KEY")
    
    # Models
    # 기본 채팅 (속도/비용 최적화)
    DEFAULT_MODEL_ID: str = "anthropic.claude-3-haiku-20240307-v1:0"
    # 로드맵 생성/질문 (고성능, Claude 3.5 Sonnet)
    ROADMAP_MODEL_ID: str = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    
    # Embedding
    # AWS Bedrock Titan Embedding v2 모델 (1536 차원)
    EMBEDDING_MODEL_ID: str = "amazon.titan-embed-text-v2:0"
    EMBEDDING_DIMENSION: int = 1024  # Titan Embedding v2의 차원

settings = Settings()
