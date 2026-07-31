#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null || { sudo apt update && sudo apt install -y python3 python3-venv; }
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
alpha-engine init
echo "Edit .env and set OPENAI_API_KEY, then run: .venv/bin/alpha-engine cycle"
