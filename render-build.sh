#!/usr/bin/env bash
set -e

# Install system packages needed by the app (OCR)
apt-get update
apt-get install -y tesseract-ocr

# Python deps and Django build steps
pip install -r requirements.txt
python manage.py collectstatic --noinput
# Migrations will run at start to ensure they target the live DB