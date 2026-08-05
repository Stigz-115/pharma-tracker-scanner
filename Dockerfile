# Official Playwright image ships Chromium + all system libs preinstalled,
# so there is no runtime browser download and none of the apt issues that bite
# Streamlit Community Cloud. The image tag is kept in lock-step with the
# Playwright version pinned in requirements.txt (1.49.0) so the preinstalled
# browser and its system libraries match exactly.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser + libs are already in the base image for this Playwright version.
# This is a no-op safety net (won't re-download if already present).
RUN python -m playwright install chromium

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", "--server.address=0.0.0.0", \
            "--server.headless=true"]
