#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
[ -f .env ] || cp .env.example .env
alpha-engine init
echo "Listo. Edita .env y ejecuta: ./scripts/simulate.sh"
