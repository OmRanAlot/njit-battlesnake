# ── Stage 1: build the C++ shared library ────────────────────────────────────
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY cpp/ cpp/

RUN g++ -std=c++17 -O2 -shared -fPIC -o libsnake.so cpp/engine.cpp

# ── Stage 2: runtime image ───────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy compiled library from builder
COPY --from=builder /build/libsnake.so .

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server
COPY server.py .

# Railway and Render inject PORT at runtime; default to 8080 if absent
ENV PORT=8080
EXPOSE 8080

# Use shell form so ${PORT} expands from the environment at container start
CMD uvicorn server:app --host 0.0.0.0 --port ${PORT}
