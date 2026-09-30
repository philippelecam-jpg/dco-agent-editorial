FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend /app/backend
COPY dist /app/dist
RUN useradd --uid 10001 --create-home rachel && mkdir /data && chown rachel /data
USER rachel
ENV DATABASE_PATH=/data/leads.sqlite3 ARTIFACT_PATH=/data/artifacts BIND_HOST=0.0.0.0
CMD ["python", "-m", "backend.server"]
