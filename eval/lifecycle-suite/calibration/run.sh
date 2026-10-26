#!/usr/bin/env bash
# Copyright (c) 2026 EGOGE
# SPDX-License-Identifier: Apache-2.0
#
# Entry point of the calibration image (README.md in this directory).
#   demo       the credential-free demonstration (stub agent, no key, no network)
#   preflight  check versions and that the key belongs to the dedicated workspace; spends nothing
#   calibrate  preflight, then the calibration run, then the secret scan
#   measure    preflight, the cost check against the spend limit (estimate.py), then the measured run as the
#              preregistration (mounted at /prereg) fixes it, then the secret scan
set -euo pipefail

# Image paths; the variables exist so tests can run this script outside the image (tests/unit/test_calibration_run.py).
suite=${CALIBRATION_SUITE_DIR:-/opt/memkernel/eval/lifecycle-suite}
runs=${CALIBRATION_RUNS_DIR:-/runs}
environment=${CALIBRATION_ENVIRONMENT:-/opt/environment.txt}
hf_home=${CALIBRATION_HF_HOME:-/opt/cache/huggingface}
calibration="$suite/calibration"
overrides=$(env | grep -E '^CALIBRATION_(SUITE_DIR|RUNS_DIR|ENVIRONMENT|HF_HOME)=' || true)
model=${CALIBRATION_MODEL:-claude-sonnet-5-5}
mode=${1:-calibrate}
run_id=${CALIBRATION_RUN_ID:-$( [ "$mode" = measure ] && echo measured || echo calibration )-$(date -u +%Y%m%dT%H%M%SZ)}
preregistration=${MEASURED_PREREGISTRATION:-/prereg/preregistration.md}

preflight() {
  if [ -n "$overrides" ]; then
    echo "WARNING: image paths overridden (tests only; recorded in the run as overrides.txt):" >&2
    printf '%s\n' "$overrides" | sed 's/^/  /' >&2
  fi
  echo "code: ${CODE_SHA:?image built without CODE_SHA}"
  echo "run.sh: sha256 $(sha256sum "$0" | cut -d' ' -f1)"
  echo "claude: $(claude --version)"
  echo "wiki-studio: $(wiki-studio --version)"
  echo "environment: $environment sha256 $(sha256sum "$environment" | cut -d' ' -f1)"
  # The server runs offline (HF_HUB_OFFLINE), so the image's cache must hold the pinned revision; check it
  # before the key is used.
  local model_dir cached
  model_dir="$hf_home/hub/models--sentence-transformers--${EMBEDDING_MODEL:?image built without EMBEDDING_MODEL}"
  cached=$(cat "$model_dir/refs/main" 2>/dev/null || true)
  if [ "$cached" != "${EMBEDDING_MODEL_REVISION:?image built without EMBEDDING_MODEL_REVISION}" ] \
    || [ ! -d "$model_dir/snapshots/$cached" ]; then
    echo "preflight: the image's cache holds embedding model revision '${cached:-none}', not the pinned" \
      "$EMBEDDING_MODEL_REVISION; refusing" >&2
    exit 1
  fi
  echo "embedding model: sentence-transformers/$EMBEDDING_MODEL revision $cached (pinned; the server runs offline)"
  probe="$runs/.write-probe-$$"
  if ! (: > "$probe") 2>/dev/null; then
    echo "preflight: $runs is not writable by uid $(id -u); on Linux run: sudo chown $(id -u):$(id -g) <host runs dir>" >&2
    return 1
  fi
  rm -f "$probe"
  if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "preflight: ANTHROPIC_API_KEY is not set (pass it with docker run -e ANTHROPIC_API_KEY)" >&2
    return 1
  fi
  if [ -z "${CALIBRATION_WORKSPACE_ID:-}" ]; then
    echo "preflight: CALIBRATION_WORKSPACE_ID is not set (the wrkspc_ id of the dedicated workspace)" >&2
    return 1
  fi
  # A model listing costs nothing; its anthropic-workspace-id header names the workspace the key runs in.
  headers=$(curl -sS -D - -o /dev/null https://api.anthropic.com/v1/models \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" -H "anthropic-version: 2023-06-01" | tr -d '\r')
  status=$(printf '%s\n' "$headers" | awk 'NR==1 {print $2}')
  workspace=$(printf '%s\n' "$headers" | awk -F': ' 'tolower($1)=="anthropic-workspace-id" {print $2}')
  if [ "$status" != "200" ]; then
    echo "preflight: the key was rejected (HTTP $status)" >&2
    return 1
  fi
  if [ "$workspace" != "$CALIBRATION_WORKSPACE_ID" ]; then
    echo "preflight: the key runs in workspace '${workspace:-unknown}', not $CALIBRATION_WORKSPACE_ID; refusing" >&2
    return 1
  fi
  echo "workspace: $workspace (matches CALIBRATION_WORKSPACE_ID)"
  echo "model: $model; spend cap: the workspace's spend limit, verified by you in the Console"
}

finish() {  # $1 = the runner's exit status; scans the run (partial output after a failure too) and exits
  local status=$1 copy scan code
  if [ -d "$runs/$run_id" ]; then
    copy=0
    cp "$environment" "$runs/$run_id/environment.txt" || copy=$?
    if [ "$copy" -ne 0 ]; then
      echo "$mode: could not copy $environment into the run (exit $copy); scanning anyway" >&2
    fi
    if [ -n "$overrides" ]; then
      printf '%s\n' "$overrides" > "$runs/$run_id/overrides.txt" || true
    fi
    if [ "$mode" = measure ]; then  # where and when the preregistration was announced (SC-5)
      printf '%s\n' "$MEASURED_ANNOUNCEMENT" > "$runs/$run_id/announcement.txt" || copy=$?
    fi
    scan=0
    python3 "$suite/scan_secrets.py" "$runs/$run_id" || scan=$?
    if [ "$scan" -ne 0 ]; then  # loud whichever exit status wins below
      echo "SECRET SCAN FOUND HITS in $runs/$run_id (exit $scan): do not commit anything from this run" >&2
    fi
    echo "$( [ "$mode" = measure ] && echo measured || echo calibration ) output: $runs/$run_id" \
      "(runner exit $status, secret scan exit $scan, environment copy exit $copy)"
    # the runner's failure is reported first, then the scan's, then the copy's
    for code in "$scan" "$copy"; do
      if [ "$status" -eq 0 ] && [ "$code" -ne 0 ]; then
        status=$code
      fi
    done
  fi
  exit "$status"
}

case "$mode" in
  demo)
    python3 "$suite/runner.py" demo
    ;;
  preflight)
    preflight
    ;;
  calibrate)
    preflight
    tasks=()
    while IFS= read -r task; do
      case "$task" in ''|'#'*) ;; *) tasks+=(--task "$task") ;; esac
    done < "$calibration/tasks.txt"
    arms=()
    for arm in bare placebo protocol claude_md fs_grep memkernel wiki_studio; do arms+=(--arm "$arm"); done
    status=0
    python3 "$suite/runner.py" run \
      "${tasks[@]}" "${arms[@]}" \
      --runs 1 --run-root "$runs" --run-id "$run_id" --phase calibration --model "$model" \
      --code-sha "$CODE_SHA" \
      --memkernel-cmd /opt/mk-venv/bin/memkernel --memkernel-python /opt/mk-venv/bin/python \
      --shared-cache /opt/cache || status=$?
    finish "$status"
    ;;
  measure)
    if [ ! -f "$preregistration" ]; then
      echo "measure: no preregistration at $preregistration (vm.sh measure mounts the one PREREG_COMMIT names)" >&2
      exit 1
    fi
    echo "preregistration: $preregistration sha256 $(sha256sum "$preregistration" | cut -d' ' -f1)"
    if [ -z "${MEASURED_ANNOUNCEMENT:-}" ]; then  # SC-5: vm.sh measure checks the #17 comment and passes it on
      echo "measure: MEASURED_ANNOUNCEMENT (the #17 comment's URL and posting time) is not set" >&2
      exit 1
    fi
    echo "announcement: $MEASURED_ANNOUNCEMENT"
    args=()
    while IFS= read -r arg; do args+=("$arg"); done \
      < <(python3 "$suite/estimate.py" --preregistration "$preregistration" --runner-args)
    [ "${#args[@]}" -gt 0 ] || { echo "measure: the preregistration names no tasks or arms" >&2; exit 1; }
    model=${args[${#args[@]}-1]}   # runner_args ends with --model MODEL: preflight prints the preregistered model
    preflight
    # The cost check spends nothing: the estimate comes from the committed calibration receipts (FR-016).
    python3 "$suite/estimate.py" --preregistration "$preregistration" --repo "$(dirname "$(dirname "$suite")")" \
      --limit "${MEASURED_SPEND_LIMIT:?MEASURED_SPEND_LIMIT, the spend limit of the workspace in USD, is required}" || exit 1
    status=0
    python3 "$suite/runner.py" run \
      "${args[@]}" --run-root "$runs" --run-id "$run_id" --phase measured --preregistration "$preregistration" \
      --code-sha "$CODE_SHA" \
      --memkernel-cmd /opt/mk-venv/bin/memkernel --memkernel-python /opt/mk-venv/bin/python \
      --shared-cache /opt/cache || status=$?
    finish "$status"
    ;;
  *)
    echo "usage: run.sh [demo|preflight|calibrate|measure]" >&2
    exit 2
    ;;
esac
