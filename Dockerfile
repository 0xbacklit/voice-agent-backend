FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default command can be overridden by START_CMD in Fly dashboard.
ENV START_CMD="uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"

CMD ["sh", "-c", "$START_CMD"]
