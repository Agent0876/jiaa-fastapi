
import sys
import os
import boto3
from botocore.exceptions import ClientError

# Add the app directory to sys.path
sys.path.append(os.getcwd())

try:
    from app.core.config import settings
    print(f"AWS Region: {settings.AWS_REGION}")
    print(f"AWS Access Key ID set: {'Yes' if settings.AWS_ACCESS_KEY_ID else 'No'}")
    print(f"AWS Secret Access Key set: {'Yes' if settings.AWS_SECRET_ACCESS_KEY else 'No'}")
    
    # Check for session token in settings or env
    session_token = os.getenv("AWS_SESSION_TOKEN")
    print(f"AWS Session Token set in env: {'Yes' if session_token else 'No'}")
    
    # Initialize client
    client_params = {
        "service_name": "bedrock-runtime",
        "region_name": settings.AWS_REGION,
        "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
    }
    if session_token:
        client_params["aws_session_token"] = session_token
        
    client = boto3.client(**client_params)
    
    # Try a simple call
    health_client = boto3.client(
        service_name="bedrock",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        aws_session_token=session_token
    )
    
    response = health_client.list_foundation_models()
    print("Successfully connected to AWS Bedrock!")
    
except ClientError as e:
    print(f"AWS ClientError: {e}")
except Exception as e:
    print(f"Error: {e}")
