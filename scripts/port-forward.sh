#!/bin/bash

# 포트 포워딩은 게이트웨이를 통해 접근하므로 더 이상 필요하지 않습니다.
# 게이트웨이를 통해 접근: http://localhost:8080/api/v1/chat/**, /api/v1/judge/**

echo "⚠️  포트 포워딩이 제거되었습니다."
echo ""
echo "게이트웨이를 통해 접근하세요:"
echo "  - AI Chat Service: http://localhost:8080/api/v1/chat/**"
echo "  - AI Judge Service: http://localhost:8080/api/v1/judge/**"
echo ""
echo "게이트웨이 포트 포워딩:"
echo "  kubectl port-forward svc/jiaa-gateway-service-svc 8080:8080 -n jiaa-backend"
