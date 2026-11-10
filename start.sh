#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STATE="$ROOT/.sentinelp2p"
RUN="$STATE/run"
LOGS="$STATE/logs"
WITH_STREAMLIT=0
for arg in "$@"; do
  case "$arg" in
    --streamlit) WITH_STREAMLIT=1 ;;
    --help|-h) echo "Usage: ./start.sh [--streamlit]"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

fail() { echo "start: $*" >&2; exit 1; }
[[ -f "$ROOT/frontend/dist/index.html" ]] || fail "Production frontend is missing. Run ./setup.sh to install dependencies and build it."
[[ -f "$STATE/python-path" ]] || fail "Python environment is not configured. Run ./setup.sh first."
PYTHON="$(cat "$STATE/python-path")"
[[ -x "$PYTHON" ]] || fail "Configured Python is unavailable: $PYTHON. Rerun ./setup.sh in the intended environment."
mkdir -p "$RUN" "$LOGS"
API_HOST="${SENTINEL_API_HOST:-127.0.0.1}"
API_PORT="${SENTINEL_API_PORT:-8000}"
STREAMLIT_PORT="${SENTINEL_STREAMLIT_PORT:-8501}"
valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 ))
}
valid_port "$API_PORT" || fail "SENTINEL_API_PORT must be an integer from 1 to 65535."
if [[ "$WITH_STREAMLIT" -eq 1 ]]; then
  valid_port "$STREAMLIT_PORT" || fail "SENTINEL_STREAMLIT_PORT must be an integer from 1 to 65535."
fi

port_is_open() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
with socket.socket() as sock:
    sock.settimeout(0.25)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}
pid_is_ours() {
  local pid="$1" expected="$2" tokenfile="${3:-}" command stored_token current_token
  kill -0 "$pid" 2>/dev/null || return 1
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  [[ "$command" == *"$expected"* ]] || return 1
  if [[ -n "$tokenfile" ]]; then
    [[ -f "$tokenfile" && -r "/proc/$pid/stat" ]] || return 1
    stored_token="$(cat "$tokenfile")"
    current_token="$(awk '{print $22}' "/proc/$pid/stat")"
    [[ -n "$stored_token" && "$stored_token" == "$current_token" ]] || return 1
  fi
}
stop_if_ours() {
  local pidfile="$1" expected="$2" tokenfile="$3" pid
  [[ -f "$pidfile" ]] || return 0
  pid="$(cat "$pidfile")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && pid_is_ours "$pid" "$expected" "$tokenfile"; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..40}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    if pid_is_ours "$pid" "$expected" "$tokenfile"; then kill -KILL "$pid" 2>/dev/null || true; fi
  fi
  rm -f -- "$pidfile"
  rm -f -- "$tokenfile"
}
assert_port_free() {
  local port="$1" service="$2" override
  case "$service" in
    api) override="SENTINEL_API_PORT" ;;
    streamlit) override="SENTINEL_STREAMLIT_PORT" ;;
    *) override="the corresponding port environment variable" ;;
  esac
  if port_is_open "$port"; then
    fail "Port $port ($service) is already in use. Stop that service or set $override to another free port."
  fi
}

API_ACTIVE=0
if [[ -f "$RUN/api.pid" ]] && pid_is_ours "$(cat "$RUN/api.pid")" "uvicorn app.main:app" "$RUN/api.start"; then
  API_COMMAND="$(ps -p "$(cat "$RUN/api.pid")" -o args= 2>/dev/null || true)"
  if [[ "$API_COMMAND" == *"--host $API_HOST --port $API_PORT"* ]]; then
    API_ACTIVE=1
    echo "FastAPI is already running at http://$API_HOST:$API_PORT"
  else
    fail "FastAPI was started by these scripts with different host/port settings. Run ./stop.sh before changing them."
  fi
fi
if [[ "$API_ACTIVE" -eq 0 ]]; then assert_port_free "$API_PORT" "api"; fi
if [[ "$WITH_STREAMLIT" -eq 1 ]]; then
  "$PYTHON" -c 'import streamlit' >/dev/null 2>&1 || fail "Streamlit is not installed. Run ./setup.sh --with-streamlit first."
  if [[ -f "$RUN/streamlit.pid" ]] && pid_is_ours "$(cat "$RUN/streamlit.pid")" "dashboard.py" "$RUN/streamlit.start"; then
    STREAMLIT_COMMAND="$(ps -p "$(cat "$RUN/streamlit.pid")" -o args= 2>/dev/null || true)"
    if [[ "$STREAMLIT_COMMAND" == *"--server.port $STREAMLIT_PORT"* ]]; then
      echo "Streamlit is already running at http://127.0.0.1:$STREAMLIT_PORT"
    else
      fail "Streamlit was started by these scripts with a different port. Run ./stop.sh before changing it."
    fi
  else
    assert_port_free "$STREAMLIT_PORT" "streamlit"
  fi
fi
if [[ "$API_ACTIVE" -eq 0 ]]; then
  export PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
  nohup "$PYTHON" -m uvicorn app.main:app --host "$API_HOST" --port "$API_PORT" \
    >>"$LOGS/api.log" 2>&1 </dev/null &
  API_PID=$!
  printf '%s\n' "$API_PID" > "$RUN/api.pid"
  awk '{print $22}' "/proc/$API_PID/stat" > "$RUN/api.start"

cleanup_on_failure() {
  stop_if_ours "$RUN/api.pid" "uvicorn app.main:app" "$RUN/api.start"
  stop_if_ours "$RUN/streamlit.pid" "dashboard.py" "$RUN/streamlit.start"
}
for _ in {1..40}; do
  if port_is_open "$API_PORT"; then break; fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    tail -n 40 "$LOGS/api.log" >&2 || true
    cleanup_on_failure
    fail "FastAPI exited during startup; see $LOGS/api.log"
  fi
  sleep 0.5
done
if [[ "$API_ACTIVE" -eq 0 ]]; then
  if ! port_is_open "$API_PORT"; then
    tail -n 40 "$LOGS/api.log" >&2 || true
    cleanup_on_failure
    fail "FastAPI did not open port $API_PORT; see $LOGS/api.log"
  fi
  if ! "$PYTHON" - "$API_HOST" "$API_PORT" <<'PY'
import sys, time, urllib.error, urllib.request
url = f"http://{sys.argv[1]}:{sys.argv[2]}/api/health"
for _ in range(20):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            if response.status == 200:
                print(response.read().decode())
                raise SystemExit(0)
    except Exception:
        time.sleep(0.25)
raise SystemExit(1)
PY
  then
    cleanup_on_failure
    fail "FastAPI is listening but /api/health failed; inspect $LOGS/api.log"
  fi
fi
fi

if [[ "$WITH_STREAMLIT" -eq 1 ]]; then
  if ! [[ -f "$RUN/streamlit.pid" ]] || ! pid_is_ours "$(cat "$RUN/streamlit.pid")" "dashboard.py" "$RUN/streamlit.start"; then
    nohup "$PYTHON" -m streamlit run "$ROOT/dashboard.py" --server.address 127.0.0.1 \
      --server.port "$STREAMLIT_PORT" --server.headless true \
      >>"$LOGS/streamlit.log" 2>&1 </dev/null &
    printf '%s\n' "$!" > "$RUN/streamlit.pid"
    awk '{print $22}' "/proc/$(cat "$RUN/streamlit.pid")/stat" > "$RUN/streamlit.start"
  fi
fi

echo "SentinelP2P is ready: http://$API_HOST:$API_PORT"
echo "API log: $LOGS/api.log"
if [[ "$WITH_STREAMLIT" -eq 1 ]]; then echo "Optional Streamlit dashboard: http://127.0.0.1:$STREAMLIT_PORT"; fi
echo "Stop with: ./stop.sh"
