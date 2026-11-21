# PocketProWS backend: FastAPI + embedded ChromaDB.
# Container port is fixed at 5003; start.sh --docker publishes it on the
# resolved host port (5003, bumped +1 past foreign holders).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY . ./backend

EXPOSE 5003

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5003/api/health')"

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5003"]
