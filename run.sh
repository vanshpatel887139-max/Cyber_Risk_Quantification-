#!/usr/bin/env bash
# Start the Cyber Risk Quantification prototype.
#
#   ./run.sh              start on http://127.0.0.1:8000
#   ./run.sh --port 9000  start on another port
#   ./run.sh --reset      rebuild the synthetic dataset before starting
set -euo pipefail

cd "$(dirname "$0")"

PORT=8000
RESET=0
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    --reset) RESET=1; shift ;;
    --test) RESET=0; exec python3 -m unittest discover -s tests -t tests ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$RESET" = "1" ]; then
  echo "Resetting the synthetic dataset (D0)..."
  python3 - <<'PY'
from app import db, demo_data
db.init_db()
with db.connect() as conn:
    print("seeded:", demo_data.seed(conn, refresh=False))
PY
fi

echo "Starting on http://127.0.0.1:${PORT}  (demo login: admin / admin123)"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
