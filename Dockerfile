FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY parser/out/ parser/out/

EXPOSE 8000
# CLOVASTUDIO_API_KEY / CLOVASTUDIO_MODEL은 docker run -e 로 주입한다 (이미지에 굽지 않는다)
CMD ["uvicorn", "agent.server:app", "--host", "0.0.0.0", "--port", "8000"]
