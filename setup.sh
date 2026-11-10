#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WITH_STREAMLIT=0
CHECK_ONLY=0

usage() {
  cat <<'EOF'
Usage: ./setup.sh [--with-streamlit] [--check-only]

  --with-streamlit  Install optional Streamlit dashboard dependencies.
  --check-only      Validate prerequisites and report actions without changing files.
EOF
}

for arg in "$@"; do
  case "$arg" in
    --with-streamlit) WITH_STREAMLIT=1 ;;
    --check-only) CHECK_ONLY=1 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; usage >&2; exit 2 ;;
  esac
done

fail() { echo "setup: $*" >&2; exit 1; }
command -v uv >/dev/null 2>&1 || fail "uv is required. Install it using the official uv installation instructions, then rerun this script."
command -v node >/dev/null 2>&1 || fail "Node.js is required (20.19+ or 22.12+). Install it manually; setup will not upgrade your system."
command -v npm >/dev/null 2>&1 || fail "npm is required. Install a supported Node.js release with npm, then rerun setup."

if [[ -n "${VIRTUAL_ENV:-}" ]]; then
  PYTHON="$VIRTUAL_ENV/bin/python"
  [[ -x "$PYTHON" ]] || fail "VIRTUAL_ENV is set but its Python executable is missing: $PYTHON"
elif [[ -n "${CONDA_PREFIX:-}" ]]; then
  PYTHON="$CONDA_PREFIX/bin/python"
  [[ -x "$PYTHON" ]] || fail "CONDA_PREFIX is set but its Python executable is missing: $PYTHON"
elif [[ -e "$ROOT/.venv" ]]; then
  [[ -x "$ROOT/.venv/bin/python" ]] || fail "An existing .venv directory has no usable Python. It was left untouched; repair or move it yourself, then rerun setup."
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3 || command -v python || true)"
  [[ -n "$PYTHON" ]] || fail "Python 3.10 or newer is required. Install it manually; setup will not upgrade system Python."
fi

python_version="$($PYTHON -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || fail "Could not run Python at $PYTHON"
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  fail "Python 3.10+ is required; found $python_version at $PYTHON. No system version was changed."
fi
node_version="$(node --version | sed 's/^v//')"
if ! node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(((a===20 && b>=19) || (a===22 && b>=12) || a>=23) ? 0 : 1)' ; then
  fail "Node.js 20.19+ or 22.12+ is required; found v$node_version. No system version was changed."
fi

echo "Python: $python_version ($PYTHON)"
echo "Node.js: v$node_version; npm: $(npm --version)"
echo "uv: $(uv --version)"
if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo "Prerequisite check complete; no files or environments were changed."
  exit 0
fi

if [[ ! -e "$ROOT/.env" ]]; then
  [[ -f "$ROOT/.env.example" ]] || fail "Root .env.example is missing; cannot create a safe default configuration."
  # noclobber makes the preserve-existing-config guarantee atomic enough to
  # protect a file created between the existence check and copy.
  if (set -o noclobber; cat "$ROOT/.env.example" > "$ROOT/.env") 2>/dev/null; then
    echo "Created .env from .env.example (only because .env did not exist)."
  else
    echo "Preserving .env created by another process."
  fi
else
  echo "Preserving existing .env."
fi

# If no environment is active or already present, make one with uv. Existing
# environments are never removed or recreated.
if [[ -z "${VIRTUAL_ENV:-}" && -z "${CONDA_PREFIX:-}" && ! -e "$ROOT/.venv" ]]; then
  uv venv --python "$PYTHON" "$ROOT/.venv"
  PYTHON="$ROOT/.venv/bin/python"
fi

uv pip install --python "$PYTHON" -r "$ROOT/backend/requirements.txt"
if [[ "$WITH_STREAMLIT" -eq 1 ]]; then
  uv pip install --python "$PYTHON" -r "$ROOT/requirements-streamlit.txt"
fi

npm ci --prefix "$ROOT/frontend"
VITE_API_BASE_URL=/api npm run build --prefix "$ROOT/frontend"

mkdir -p "$ROOT/.sentinelp2p"
printf '%s\n' "$PYTHON" > "$ROOT/.sentinelp2p/python-path"
echo "Setup complete. Ollama is optional and was not installed or started. Set OLLAMA_MODEL in .env only after installing a model yourself."
if [[ "$WITH_STREAMLIT" -eq 1 ]]; then
  echo "Optional Streamlit dependencies are installed. Start that UI separately with: ./start.sh --streamlit"
fi
echo "Run the main application with: ./start.sh"
