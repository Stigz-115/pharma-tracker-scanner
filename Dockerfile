# Official Playwright image ships Chromium + all system libs preinstalled,
# so there is no runtime browser download (unlike Streamlit Community Cloud).
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browser is already in the base image; ensure the pinned version is present.
RUN python -m playwright install chromium

COPY . .

EXPOSE 8501

HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app.py", \
            "--server.port=8501", "--server.address=0.0.0.0", \
            "--server.headless=true"]
