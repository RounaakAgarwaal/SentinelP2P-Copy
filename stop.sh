#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
RUN="$ROOT/.sentinelp2p/run"

stop_pidfile() {
  local name="$1" expected="$2" pidfile="$RUN/$1.pid" tokenfile="$RUN/$1.start" pid command stored_token current_token
  [[ -f "$pidfile" ]] || { echo "$name is not running (no script-owned PID record)."; return 0; }
  pid="$(cat "$pidfile")"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$pidfile" "$tokenfile"
    echo "Removed stale $name PID record."
    return 0
  fi
  command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
  stored_token="$(cat "$tokenfile" 2>/dev/null || true)"
  current_token="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
  if [[ "$command" != *"$expected"* || -z "$stored_token" || "$stored_token" != "$current_token" ]]; then
    echo "Refusing to stop PID $pid: it no longer matches this script's $name process." >&2
    return 1
  fi
  kill "$pid"
  for _ in {1..40}; do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    command="$(ps -p "$pid" -o args= 2>/dev/null || true)"
    current_token="$(awk '{print $22}' "/proc/$pid/stat" 2>/dev/null || true)"
    if [[ "$command" == *"$expected"* && "$current_token" == "$stored_token" ]]; then kill -KILL "$pid"; fi
  fi
  rm -f -- "$pidfile" "$tokenfile"
  echo "Stopped $name (PID $pid)."
}

stop_pidfile api "uvicorn app.main:app"
stop_pidfile streamlit "dashboard.py"
