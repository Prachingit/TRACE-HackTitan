# Stage 1: build the React frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: FastAPI serving API and built frontend on one origin
FROM python:3.11-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist ./static
ENV ENV=production \
    PORT=8000 \
    DATA_DIR=/data/uploads \
    DATABASE_URL=sqlite:////data/trace.db
VOLUME ["/data"]
EXPOSE 8000
# SECRET_KEY must be provided at runtime: docker run -e SECRET_KEY=... -v trace-data:/data -p 8000:8000 trace
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
