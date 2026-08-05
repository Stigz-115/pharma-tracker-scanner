#!/usr/bin/env bash
# One-shot local setup + launch. Creates a venv, installs deps + Chromium, runs the app.
set -e

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium

echo ""
echo "Setup complete. Launching Streamlit..."
streamlit run app.py
