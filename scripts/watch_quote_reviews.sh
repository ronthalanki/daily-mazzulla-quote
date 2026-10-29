#!/usr/bin/env bash
# Hourly polling uses GitHub reads and local state; Codex is queued only for feedback.
set -euo pipefail
umask 077
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
QUEUE_DIR=${MAZZULLA_REVIEW_DIR:-"$REPO_ROOT/review-queue"}
mkdir -p -- "$QUEUE_DIR/logs"
if [[ -f "$QUEUE_DIR/cron.env" ]]; then
  source "$QUEUE_DIR/cron.env"
fi
export MAZZULLA_ORIGIN_THREAD
CODEX_EXECUTABLE=${MAZZULLA_CODEX_BIN:-codex}
FINALIZER_TIMEOUT=${MAZZULLA_FINALIZER_TIMEOUT_SECONDS:-120}
exec 9>"$QUEUE_DIR/.watcher.lock"
flock -n 9 || exit 0
RUN_LOG="$QUEUE_DIR/logs/pr-watch-$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
exec >>"$RUN_LOG" 2>&1
STAGING_DIR=$(mktemp -d "${TMPDIR:-/tmp}/mazzulla-pr-watch.XXXXXXXX")
trap 'rm -rf -- "$STAGING_DIR"' EXIT
source "$REPO_ROOT/scripts/review_inbox.sh"
printf 'PR polling started at %s\n' "$(date -u --iso-8601=seconds)"
if ! timeout --kill-after=10s 900s python3 "${MAZZULLA_PR_SCRIPT:-$REPO_ROOT/scripts/quote_review_pr.py}" \
  --queue-dir "$QUEUE_DIR" poll >"$STAGING_DIR/poll-result.json"; then
  cat "$STAGING_DIR/poll-result.json"
  finalize_inbox needs-action "Mazzulla PR review automation needs attention; check its local watcher log." || \
    printf 'Inbox finalizer failed; local logs retain the error.\n'
  exit 1
fi
cat "$STAGING_DIR/poll-result.json"
mapfile -t CLOSED_PRS < <(python3 -c 'import json,sys; print("\n".join(str(item["number"]) for item in json.load(open(sys.argv[1])).get("closed_prs", [])))' "$STAGING_DIR/poll-result.json")
if [[ -n "${CLOSED_PRS[0]:-}" ]]; then
  exec 8>"$QUEUE_DIR/.weekly.lock"
  # Defer cleanup to the next poll while research is running.
  if flock -n 8; then
    if finalize_closed_reviews "$STAGING_DIR/poll-result.json"; then
      python3 "${MAZZULLA_PR_SCRIPT:-$REPO_ROOT/scripts/quote_review_pr.py}" --queue-dir "$QUEUE_DIR" notices-done "${CLOSED_PRS[@]}"
    else
      printf 'Closed PR notice cleanup failed; it will be retried.\n'
      exit 1
    fi
  fi
fi
printf 'PR polling completed at %s\n' "$(date -u --iso-8601=seconds)"
