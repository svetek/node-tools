#!/usr/bin/env bash

set -uo pipefail

DATA_PATH="${HL_DATA_PATH:-${HOME}/hl/data}"
MAX_AGE_HOURS="${HL_PRUNE_MAX_AGE_HOURS:-6}"
INTERVAL_SECONDS="${HL_PRUNE_INTERVAL_SECONDS:-3600}"
EXCLUDES_RAW="${HL_PRUNE_EXCLUDES:-visor_child_stderr}"

MAX_AGE_MINUTES=$(( MAX_AGE_HOURS * 60 ))

read -r -a EXCLUDES <<< "${EXCLUDES_RAW}"

PRUNE_ARGS=()
for dir in "${EXCLUDES[@]}"; do
  [ -n "${dir}" ] || continue
  PRUNE_ARGS+=(-path "*/${dir}" -prune -o)
done

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

log "pruner started: path=${DATA_PATH} max_age_hours=${MAX_AGE_HOURS} interval=${INTERVAL_SECONDS}s excludes='${EXCLUDES_RAW}'"

while true; do
  if [ ! -d "${DATA_PATH}" ]; then
    log "data directory ${DATA_PATH} does not exist yet, waiting"
    sleep "${INTERVAL_SECONDS}"
    continue
  fi

  size_before="$(du -sh "${DATA_PATH}" 2>/dev/null | cut -f1)"

  find "${DATA_PATH}" -mindepth 1 "${PRUNE_ARGS[@]}" -type f -mmin "+${MAX_AGE_MINUTES}" -exec rm -f {} + 2>/dev/null

  # Keep empty directories: hl-node can create a log directory before opening
  # its first file, so removing it here can race with the node and crash it.

  size_after="$(du -sh "${DATA_PATH}" 2>/dev/null | cut -f1)"
  log "prune done: ${size_before} -> ${size_after}"

  sleep "${INTERVAL_SECONDS}"
done
