# The MedTracker sync server. Built from the repository root (see docker-compose.yml),
# because it shares sync_schema.py with the app.
FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY sync_schema.py .
COPY server/sync_server ./sync_server
RUN useradd --system --no-create-home medtracker
USER medtracker
EXPOSE 8000
CMD ["python", "-m", "sync_server.app"]
