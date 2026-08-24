FROM python:3.11-slim

# 파이썬 로그가 버퍼에 갇히면 장애 때 원인을 못 본다. 평가 기간 2주간
# 상시 운영되므로 stdout이 즉시 나가야 한다.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY parser/out/ parser/out/

EXPOSE 8000

# 컨테이너가 살아는 있는데 응답을 못 하는 상태를 구분한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"

# CLOVASTUDIO_API_KEY / CLOVASTUDIO_MODEL은 docker run -e 로 주입한다 (이미지에 굽지 않는다)
CMD ["uvicorn", "agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
