FROM python:3.14-slim

WORKDIR /code

# Install git (required by Hugging Face Spaces build infrastructure)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /usr/sbin/nologin appuser

# Install CPU-only PyTorch first (much smaller than full torch)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
# NOTE: SECRET_KEY must be provided at runtime (e.g. `docker run -e SECRET_KEY=...`
# or via the platform's secret store). The app refuses to start without it unless
# DEBUG=true is set. See .env.example.
COPY . .

# Writable data dir for SQLite / ai_settings (volume-mounted in many hosts).
RUN mkdir -p /code/user_data && chown -R appuser:appuser /code

USER appuser

# HF Spaces expects port 7860
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
