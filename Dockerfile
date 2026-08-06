FROM python:3.14-slim

WORKDIR /code

# git: some pip installs resolve VCS refs during the build.
# Verify the build still succeeds before removing this.
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

# 7860 matches run_dev.sh and the Cloudflare Tunnel origin.
EXPOSE 7860

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
