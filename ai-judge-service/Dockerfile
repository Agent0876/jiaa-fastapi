FROM public.ecr.aws/amazonlinux/amazonlinux:2023

WORKDIR /app

# Python 및 시스템 의존성 설치
RUN dnf install -y \
    python3.12 \
    python3.12-pip \
    gcc \
    libffi-devel \
    && dnf clean all

# Python 의존성 복사 및 설치
COPY requirements.txt* ./
RUN if [ -f requirements.txt ]; then python3.12 -m pip install --no-cache-dir -r requirements.txt; fi

# 애플리케이션 코드 복사
COPY . .

# 포트 노출
EXPOSE 8080

# 애플리케이션 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

