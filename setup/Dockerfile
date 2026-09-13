FROM python:3.11-slim

WORKDIR /app

# System deps for vosk, sounddevice, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 libportaudio2 portaudio19-dev gcc && \
    rm -rf /var/lib/apt/lists/*

COPY vendor/irene-va/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    fastapi uvicorn[standard] fastapi-utils websockets

COPY vendor/irene-va/ /app/vendor/irene-va/

WORKDIR /app/vendor/irene-va
EXPOSE 5003 2700

CMD ["python", "runva_webapi.py"]
