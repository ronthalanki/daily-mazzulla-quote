#!/usr/bin/env bash
# Shared existing Agent Inbox finalizer; callers provide a private staging directory.
finalize_inbox() {
  local state=$1
  local summary=$2
  if [[ -z "${MAZZULLA_ORIGIN_THREAD:-}" ]]; then
    printf 'Inbox finalization failed: configure MAZZULLA_ORIGIN_THREAD in review-queue/cron.env.\n'
    return 1
  fi
  # Build a trusted command with shell quoting; no web/model output enters it.
  python3 - "$MAZZULLA_ORIGIN_THREAD" "$state" "$summary" >"$STAGING_DIR/finalizer.txt" <<'PY'
import shlex
import sys
command = shlex.join(["codex-inbox", "set", "--thread", sys.argv[1], "--project",
                      "daily-mazzulla-quote", sys.argv[2], sys.argv[3]])
print("You are the ephemeral root finalizer for a completed local cron run. Run exactly this trusted command:")
print(command)
print("Do no other work: no research, file inspection, code changes, agents, or manual notifications. "
      "Do not resolve the item first. Then finish with a short confirmation. The existing configured "
      "agent-turn-complete callback handles notification. Do not modify or invoke that callback manually.")
PY
  timeout --kill-after=10s "${FINALIZER_TIMEOUT}s" "$CODEX_EXECUTABLE" exec \
    --ephemeral --skip-git-repo-check --cd "$STAGING_DIR" --color never \
    - <"$STAGING_DIR/finalizer.txt"
}


# Root-only finalizer for notices whose PR was closed/merged. The watcher holds
# the weekly runner lock so a new scheduled PR notice cannot race this cleanup.
finalize_closed_reviews() {
  local result=$1
  if [[ -z "${MAZZULLA_ORIGIN_THREAD:-}" ]]; then
    printf 'Inbox cleanup failed: MAZZULLA_ORIGIN_THREAD is not configured.\n'
    return 1
  fi
  python3 - "$MAZZULLA_ORIGIN_THREAD" "$result" >"$STAGING_DIR/cleanup-finalizer.txt" <<'PYCODE'
import json
import shlex
import sys
thread = sys.argv[1]
closed = json.load(open(sys.argv[2]))["closed_prs"]
summaries = ["Mazzulla candidates are ready for review: " + item["url"] +
             "; comment to revise and merge to publish." for item in closed]
program = "\n".join([
    "import json, subprocess",
    "items = json.loads(subprocess.run(['codex-inbox', 'list', '--json'], check=True, capture_output=True, text=True).stdout)",
    "matches = [item for item in items if item.get('thread_id') == " + repr(thread) +
    " and item.get('project') == 'daily-mazzulla-quote' and item.get('kind') == 'ready-for-review' and item.get('summary') in " + repr(summaries) + "]",
    "if matches: subprocess.run(['codex-inbox', 'resolve', '--thread', " + repr(thread) + "], check=True)",
])
print("You are the ephemeral root finalizer for closed Mazzulla review PRs. Run exactly this trusted conditional cleanup command:")
print(shlex.join(["python3", "-c", program]))
print("It resolves only an exact generated notice for a closed PR. Preserve unrelated items. Do no other work, agents, research, or notifications. Finish with a short confirmation; the existing callback handles notification state.")
PYCODE
  timeout --kill-after=10s "${FINALIZER_TIMEOUT}s" "$CODEX_EXECUTABLE" exec \
    --ephemeral --skip-git-repo-check --cd "$STAGING_DIR" --color never \
    - <"$STAGING_DIR/cleanup-finalizer.txt"
}
