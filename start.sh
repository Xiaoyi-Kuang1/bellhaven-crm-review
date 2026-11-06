#!/usr/bin/env bash
# Start the local reviewer in preview mode unless --enable-writes is explicit.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10 or newer is required"'
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python - <<'PY'
from importlib.metadata import version, PackageNotFoundError
import sys
from pathlib import Path
try:
    for requirement in Path('requirements.txt').read_text().splitlines():
        if requirement.strip():
            name, expected = requirement.split('==')
            if version(name) != expected: sys.exit(1)
except PackageNotFoundError:
    sys.exit(1)
PY
then
  .venv/bin/python -m pip install -r requirements.txt
fi
mkdir -p data
if [[ ! -f data/review.sqlite3 ]]; then
  if [[ -z "${BELLHAVEN_API_TOKEN:-}" ]]; then
    echo 'No review database found. Set BELLHAVEN_API_TOKEN and rerun to discover evidence first.' >&2
    exit 1
  fi
  .venv/bin/python daily.py
fi
exec .venv/bin/python review.py "$@"
