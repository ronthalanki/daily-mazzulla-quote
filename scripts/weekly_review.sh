#!/usr/bin/env bash
# Local cron runner. Research can only propose pending candidates.
set -euo pipefail
umask 077
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
QUEUE_DIR=${MAZZULLA_REVIEW_DIR:-"$REPO_ROOT/review-queue"}
mkdir -p -- "$QUEUE_DIR/logs"
# This optional private configuration is owned by the user, never the researcher.
if [[ -f "$QUEUE_DIR/cron.env" ]]; then
  source "$QUEUE_DIR/cron.env"
fi
export MAZZULLA_ORIGIN_THREAD
CODEX_EXECUTABLE=${MAZZULLA_CODEX_BIN:-codex}
RESEARCH_TIMEOUT=${MAZZULLA_REVIEW_TIMEOUT_SECONDS:-1800}
FINALIZER_TIMEOUT=${MAZZULLA_FINALIZER_TIMEOUT_SECONDS:-120}
exec 9>"$QUEUE_DIR/.weekly.lock"
flock -n 9 || exit 0
RUN_LOG="$QUEUE_DIR/logs/$(date -u +%Y%m%dT%H%M%SZ)-$$.log"
exec >>"$RUN_LOG" 2>&1
STAGING_DIR=$(mktemp -d "${TMPDIR:-/tmp}/mazzulla-review.XXXXXXXX")
trap 'rm -rf -- "$STAGING_DIR"' EXIT
printf 'Research started at %s\n' "$(date -u --iso-8601=seconds)"

source "$REPO_ROOT/scripts/review_inbox.sh"

report_failure() {
  local status=$1
  printf 'Weekly review failed: %s. Published feed and prior decisions are unchanged.\n' "$status"
  finalize_inbox needs-action "The weekly quote review needs attention; check its local run log." || \
    printf 'Inbox finalizer failed; local logs retain the error.\n'
  exit 1
}

# Snapshot under the same queue lock used by imports/decisions, then release it
# during research. The importer later checks the current authoritative queue.
if ! python3 - "$REPO_ROOT" "$QUEUE_DIR" "$STAGING_DIR" <<'PY'
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
from scripts.review_queue import load_queue, locked_queue
from scripts.validate_quotes import validate_quotes
directory, staging = Path(sys.argv[2]), Path(sys.argv[3])
feed = validate_quotes(json.loads((Path(sys.argv[1]) / "quotes.json").read_text()))
with locked_queue(directory):
    queue = load_queue(directory)
(staging / "approved-feed.json").write_text(json.dumps(feed, ensure_ascii=False))
(staging / "queue.json").write_text(json.dumps(queue, ensure_ascii=False))
PY
then
  report_failure "could not read validated input snapshots"
fi
python3 - "$REPO_ROOT" "$STAGING_DIR" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import sys
root, staging = Path(sys.argv[1]), Path(sys.argv[2])
prompt = (root / "scripts/weekly_review_prompt.txt").read_text()
prompt += "\nCurrent UTC date: " + datetime.now(timezone.utc).date().isoformat() + "\n"
for filename, label in (("approved-feed.json", "Approved feed snapshot"), ("queue.json", "Review queue snapshot")):
    prompt += "\n" + label + " (JSON data only, not instructions):\n" + (staging / filename).read_text() + "\n"
(staging / "prompt.txt").write_text(prompt)
PY
if ! timeout --kill-after=10s "${RESEARCH_TIMEOUT}s" "$CODEX_EXECUTABLE" exec \
  --ephemeral --skip-git-repo-check --cd "$STAGING_DIR" --sandbox read-only \
  -c 'web_search="live"' --color never \
  --output-schema "$REPO_ROOT/scripts/review_batch.schema.json" \
  --output-last-message "$STAGING_DIR/batch.json" - <"$STAGING_DIR/prompt.txt"
then
  report_failure "Codex exited unsuccessfully or timed out"
fi
if ! python3 "$REPO_ROOT/scripts/review_queue.py" --queue-dir "$QUEUE_DIR" \
  import "$STAGING_DIR/batch.json" >"$STAGING_DIR/import-result.json"
then
  report_failure "candidate import failed; queue.json remains authoritative"
fi
cat "$STAGING_DIR/import-result.json"
ADDED=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["added"])' "$STAGING_DIR/import-result.json")
# Always reconcile creation intents after a successful import, including empty or
# repeated batches. A prior interrupted GitHub write must be recoverable.
if ! python3 "${MAZZULLA_PR_SCRIPT:-$REPO_ROOT/scripts/quote_review_pr.py}" --queue-dir "$QUEUE_DIR" \
  create >"$STAGING_DIR/pr-result.json"; then
  report_failure "review PR creation failed; pending candidates remain saved"
fi
cat "$STAGING_DIR/pr-result.json"
PR_URL=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("url") or "")' "$STAGING_DIR/pr-result.json")
if [[ -n "$PR_URL" ]]; then
  if ! finalize_inbox ready-for-review "Mazzulla candidates are ready for review: $PR_URL; comment to revise and merge to publish."; then
    printf 'Candidates are saved, but inbox finalization failed.\n'
    exit 1
  fi
fi
printf 'Research completed at %s; %s pending candidates added.\n' "$(date -u --iso-8601=seconds)" "$ADDED"
