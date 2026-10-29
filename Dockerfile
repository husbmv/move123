FROM node:22-alpine AS web
WORKDIR /build
COPY desktop/web/package*.json ./
RUN npm ci
COPY desktop/web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data CLOUD123_HOST=0.0.0.0 CLOUD123_PORT=12315 CLOUD123_WEB_AUTH=1 CLOUD123_ADMIN_DIR=/app/desktop/web/dist
WORKDIR /app
COPY desktop/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && useradd -r -u 10001 -m cloud123 && mkdir /data && chown cloud123:cloud123 /data
COPY desktop/backend/ /app/desktop/backend/
COPY --from=web /build/dist /app/desktop/web/dist
USER cloud123
WORKDIR /app/desktop/backend
EXPOSE 12315
CMD ["python", "-m", "app"]
