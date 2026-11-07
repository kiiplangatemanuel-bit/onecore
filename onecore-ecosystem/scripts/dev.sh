#!/usr/bin/env sh
set -eu
[ -f .env ] || cp .env.example .env
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
