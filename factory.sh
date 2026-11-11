#!/usr/bin/env bash
# factory.sh — the workshop software factory.
# Usage: ./factory.sh <issue-number>
#
# A ticket goes in, a pull request comes out. Four agents run one after another, each in a
# FRESH claude session. They share nothing but the files they write in .factory/:
#
#   1 planner   issue           → .factory/plan.md     (a human approves or denies the plan)
#   2 builder   plan            → code + .factory/build.md
#   3 checker   plan + diff     → .factory/report.md   (then your gates/ run)
#   4 reviewer  plan + report   → .factory/review.md   (APPROVE → PR, REJECT → draft [REJECTED] PR)
#
# What you change lives elsewhere: AGENTS.md (the rules), .claude/agents/<name>.md (who each
# agent is), gates/ (your checks), factory.conf (test and lint commands, scope, model).
# This engine stays the same in every repo: prompts state intent, this script enforces the rules.
#
# Reading order: CONFIG → THE PIPELINE (main) → the steps → machinery. Permissions: lib/conf.sh.
#
# Optional env:
#   FACTORY_AUTO_APPROVE=1  skip the human approval of the plan (unattended rehearsals)
#   FACTORY_NO_PUSH=1       commit locally, skip push + PR (rehearsals)
#   FACTORY_MODEL=<id>      override MODEL from factory.conf
#   FACTORY_MAX_TURNS=N     override MAX_TURNS (default 40)
#   FACTORY_TIMEOUT=N       seconds per phase (default 300), needs timeout or gtimeout
set -euo pipefail

# ═════════════════════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════════════════════════════════

ISSUE="${1:-}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
# shellcheck source=lib/events.sh
source lib/events.sh
# shellcheck source=lib/conf.sh
source lib/conf.sh
# shellcheck source=lib/gates.sh
source lib/gates.sh
# shellcheck source=lib/github.sh
source lib/github.sh
# Claude Code updates itself in the background, and the update removes the claude binary for a
# moment. The factory's own sessions never update; run_phase waits out an update started elsewhere.
export DISABLE_AUTOUPDATER=1

AGENTS=(planner builder checker reviewer)  # phase N runs .claude/agents/${AGENTS[N-1]}.md
PHASE_NAMES=(Plan Build Check Review)
DECISION_FILE=".factory/decision.json"     # the human's plan decision, written by the panel

FACTORY_BASE_REF="main"
FACTORY_BASE=""
UPSTREAM=""
ISSUE_TITLE=""
BRANCH=""
STOPPED_BY=""
TOTAL_TURNS=0
TOTAL_COST=0
PHASE_TURNS=0
PHASE_COST=0
PHASE_SECONDS=0
DECISION=""
FEEDBACK=""
PLAN_ROUND=1
PLAN_NOTES=""  # every denial's feedback, one "- " line each

# Appended to every task: chained commands are checked part by part and get denied.
SHELL_RULE="Run exactly one shell command per Bash call, with no ;, &&, || or pipes. Use the Read tool to read files."

# ═════════════════════════════════════════════════════════════════════════════════════════════
# THE PIPELINE — start reading here
# ═════════════════════════════════════════════════════════════════════════════════════════════

main() {
  start_run                      # clean .factory/, preflight checks, create the run branch

  plan_until_approved            # phase 1, repeated until a human approves the plan

  run_phase 2 .factory/build.md "Build the approved plan in .factory/plan.md for GitHub issue #${ISSUE} in ${UPSTREAM}."
  if check_scope 2; then
    run_phase 3 .factory/report.md "Check the change built for GitHub issue #${ISSUE} in ${UPSTREAM}."
    if check_scope 3 && run_gates; then
      local reviewed
      reviewed="$(code_fingerprint)"
      run_phase 4 .factory/review.md "Review the change built for GitHub issue #${ISSUE} in ${UPSTREAM}."
      if [[ "$(code_fingerprint)" != "$reviewed" ]]; then
        CURRENT_PHASE=4
        die "phase 4 changed the code it was reviewing; a reviewer may only write .factory/review.md"
      fi
    fi
  fi

  ship                           # APPROVE → PR, REJECT → draft [REJECTED] PR; a human decides the merge
}

start_run() {
  rm -rf .factory/logs .factory/*.md .factory/pr-body.md "$DECISION_FILE"
  mkdir -p .factory/logs
  # Run files never dirty the repo, whatever its .gitignore says (a "*" file ignores itself too).
  [[ -e .factory/.gitignore ]] || printf '*\n' >.factory/.gitignore
  install_traps
  telemetry_init .factory/logs
  emit run_start issue="$ISSUE"
  preflight
  git checkout -q -b "$BRANCH"
  ON_STOP=park_run
  printf 'On branch %s · upstream %s · live agent output below · raw logs in .factory/logs/\n' "$BRANCH" "$UPSTREAM"
}

# Phase 1, then the human gate. A denial re-runs the planner with every piece of feedback so far.
plan_until_approved() {
  local task="Plan GitHub issue #${ISSUE} in ${UPSTREAM}."
  while :; do
    run_phase 1 .factory/plan.md "$task"
    [[ -z "$(git status --porcelain)" ]] || die "phase 1 changed files; the plan phase may only write .factory/plan.md"
    [[ -z "${FACTORY_AUTO_APPROVE:-}" ]] || return 0

    await_plan_decision "$PLAN_ROUND"
    if [[ "$DECISION" == "approve" ]]; then
      emit plan_approved round="$PLAN_ROUND"
      printf '\n✓ plan approved by a human (round %s) · building it\n' "$PLAN_ROUND"
      return 0
    fi

    emit plan_denied round="$PLAN_ROUND" feedback="$FEEDBACK"
    printf '\n✗ plan denied: %s\n  writing a new plan with that feedback\n' "$FEEDBACK"
    # Keep the denied plan and its log for the next round (and the panel's cost).
    mv .factory/plan.md ".factory/logs/plan.round${PLAN_ROUND}.md"
    mv .factory/logs/phase1.jsonl ".factory/logs/phase1.round${PLAN_ROUND}.jsonl"
    PLAN_NOTES+="- ${FEEDBACK}"$'\n'
    task="Plan GitHub issue #${ISSUE} in ${UPSTREAM}. A human denied your previous plan \
(.factory/logs/plan.round${PLAN_ROUND}.md, read it first). Their feedback on every plan so far, oldest first:
${PLAN_NOTES}"
    PLAN_ROUND=$((PLAN_ROUND + 1))
  done
}

ship() {
  if [[ -z "$STOPPED_BY" ]] && verdict_is_approve && check_scope final; then
    printf '\n══ verdict APPROVE ══\n'
    end_run APPROVE
  else
    printf '\n══ verdict REJECT · see .factory/review.md ══\n'
    end_run REJECT
  fi
}

# ═════════════════════════════════════════════════════════════════════════════════════════════
# THE STEPS — preflight, one phase, the human gate, the checks between phases
# ═════════════════════════════════════════════════════════════════════════════════════════════

preflight() {
  local cmd agent
  [[ "$ISSUE" =~ ^[0-9]+$ ]] || die "issue must be a number, got '$ISSUE'. Usage: ./factory.sh <issue-number>"
  for cmd in claude gh jq git; do
    command -v "$cmd" >/dev/null || die "missing command: $cmd (run ./doctor.sh)"
  done
  load_conf
  for agent in "${AGENTS[@]}"; do
    [[ -s ".claude/agents/${agent}.md" ]] \
      || die "agent file missing: .claude/agents/${agent}.md (restore it: git checkout upstream/main -- .claude/agents/${agent}.md)"
  done
  if [[ -d prompts ]]; then
    printf 'Note: prompts/ is no longer read. Each phase runs an agent from .claude/agents/; move any changes there.\n' >&2
  fi
  [[ "$(git branch --show-current)" == "main" ]] || die "start from main: git checkout main"
  if [[ -n "$(git status --porcelain)" ]]; then
    die "working tree is not clean. Commit your changes first: git add gates .claude/agents AGENTS.md && git commit -m \"my factory\"" \
      "$(git status --short)"
  fi
  local problem
  problem="$(check_gate_files)" || die "$problem"
  gh auth status >/dev/null 2>&1 || die "gh is not logged in: gh auth login, then ./doctor.sh"
  detect_upstream
  [[ "$(gh issue view "$ISSUE" --repo "$UPSTREAM" --json state -q .state 2>/dev/null)" == "OPEN" ]] \
    || die "issue #$ISSUE does not exist in $UPSTREAM or is not open"
  ISSUE_TITLE="$(gh issue view "$ISSUE" --repo "$UPSTREAM" --json title -q .title | tr '\n\r' '  ' | sed 's/ *$//')"
  bash -c "$TEST_CMD" >/dev/null 2>&1 || die "tests already fail on main ($TEST_CMD): fix them before running the factory"
  if [[ -n "$(git status --porcelain)" ]]; then  # else the agents get blamed for these files
    die "running the tests ($TEST_CMD) leaves files git does not ignore. Add them to .gitignore and commit:" \
      "$(git status --short)"
  fi
  BRANCH="factory/issue-${ISSUE}-$(date +%Y%m%d-%H%M%S)"
  if branch_taken "$BRANCH"; then  # two runs in the same second
    sleep 1
    BRANCH="factory/issue-${ISSUE}-$(date +%Y%m%d-%H%M%S)"
    ! branch_taken "$BRANCH" || die "branch $BRANCH already exists; wait a second and run again"
  fi
  FACTORY_BASE="$(git rev-parse HEAD)"
  RUN_TIER="$(compute_tier)"
  emit preflight ok=true title="$ISSUE_TITLE" branch="$BRANCH" upstream="$UPSTREAM"
}

# run_phase <num> <contract file it must write> <task>: run that phase's agent in a fresh session.
run_phase() {
  local num="$1" out="$2" task="$3" agent name rule wrapper log=".factory/logs/phase$1.jsonl"
  local -a allowed=() denied=()
  agent="${AGENTS[$((num - 1))]}"
  name="${PHASE_NAMES[$((num - 1))]}"
  while IFS= read -r rule; do allowed+=("$rule"); done < <(allowed_tools "$num")
  while IFS= read -r rule; do denied+=("$rule"); done < <(denied_tools "$num")
  wait_for_claude
  # --agent loads .claude/agents/<agent>.md: the agent's prompt and its tool set.
  # --strict-mcp-config and --setting-sources project keep the participant's own connectors, plugins,
  # hooks, CLAUDE.md and .claude/settings.local.json out: only the repo's committed setup applies.
  local -a cmd=(claude -p --agent "$agent" --permission-mode acceptEdits --max-turns "$MAX_TURNS" --model "$MODEL"
    --strict-mcp-config --setting-sources project --output-format stream-json --verbose
    --disallowedTools "${denied[@]}" --allowedTools "${allowed[@]}" -- "$task $SHELL_RULE")
  wrapper="$(timeout_cmd)"
  # --foreground keeps claude in our process group so Ctrl+C still stops it.
  if [[ -n "$wrapper" ]]; then cmd=("$wrapper" --foreground -k 10 "$PHASE_TIMEOUT" "${cmd[@]}"); fi

  CURRENT_PHASE="$num"
  emit phase_start phase="$num" name="$name" agent="$agent" tools="$(IFS='|'; echo "${allowed[*]}")"
  printf '\n══ phase %s · %s · agent %s ══\n' "$num" "$name" "$agent"
  local status=0 subtype
  "${cmd[@]}" </dev/null | tee "$log" | jq -R -r --unbuffered --arg root "$ROOT/" "fromjson? | $FILTER" || status=$?
  subtype="$(jq -Rrs '[split("\n")[] | fromjson? | select(.type == "result")] | last | .subtype // ""' "$log")"
  if [[ -n "$subtype" && "$subtype" != "success" ]]; then
    die "phase $num did not finish cleanly ($subtype), e.g. hit the turn limit (raw log: $log)"
  fi
  [[ "$status" -eq 0 && -n "$subtype" ]] || die "phase $num crashed or timed out (raw log: $log)"
  [[ -s "$out" ]] || die "phase $num did not write $out, stopping before the next phase builds on nothing"
  add_totals "$log"
  emit phase_end phase="$num" turns="$PHASE_TURNS" cost_usd="$PHASE_COST" seconds="$PHASE_SECONDS"
  CURRENT_PHASE=""
}

# await_plan_decision <round>: wait for the human's answer on .factory/plan.md, from the panel
# (.factory/decision.json) or typed in this terminal. Sets DECISION (approve|deny) and FEEDBACK.
await_plan_decision() {
  local round="$1" line="" tty=""
  rm -f "$DECISION_FILE"
  emit plan_review round="$round"
  printf '\n══ plan ready (round %s) · read .factory/plan.md, then approve or deny it ══\n' "$round"
  printf 'In the panel (http://127.0.0.1:8001), or type here:  y + Enter approves  ·  n <what to change> + Enter denies\n'
  if { exec 3</dev/tty; } 2>/dev/null; then
    tty=1
  else
    printf 'No terminal to type in: answer in the panel, or stop (Ctrl+C) and run again with FACTORY_AUTO_APPROVE=1.\n'
  fi
  while :; do
    if jq -e --argjson r "$round" '.round == $r' "$DECISION_FILE" >/dev/null 2>&1; then
      DECISION="$(jq -r .decision "$DECISION_FILE")"
      FEEDBACK="$(jq -r .feedback "$DECISION_FILE")"
      printf '  panel: %s\n' "$DECISION"
      break
    fi
    if [[ -z "$tty" ]]; then
      sleep 1
    elif read -r -t 1 line <&3; then
      case "$line" in
        y | Y | yes | approve) DECISION=approve FEEDBACK="" && break ;;
        [nN]\ *[![:space:]]*) DECISION=deny FEEDBACK="$(sed -E 's/^[nN] +//' <<<"$line")" && break ;;
        *) printf '  y approves · n <what to change> denies (the feedback is required)\n' ;;
      esac
    fi
  done
  if [[ -n "$tty" ]]; then exec 3<&-; fi
  rm -f "$DECISION_FILE"
}

# check_scope <label>: only SCOPE may change. A violation writes a rejecting review.md and returns 1.
check_scope() {
  local changed bad="" f
  git add -N .  # intent-to-add makes new files visible to git diff
  changed="$(git -c core.quotepath=off diff --no-renames --name-only "$FACTORY_BASE")"
  [[ -n "$changed" ]] || die "no changes under SCOPE ($SCOPE), nothing to ship"
  while IFS= read -r f; do
    in_scope "$f" || bad+="$f"$'\n'
  done <<<"$changed"
  bad="${bad%$'\n'}"
  if [[ -n "$bad" ]]; then
    emit scope after="$1" ok=false files="$bad"
    STOPPED_BY="scope"
    {
      printf '# Scope check stopped the run\n\nOnly these paths may change: %s\n\nOut of scope:\n\n' "$SCOPE"
      # shellcheck disable=SC2016  # literal backticks: Markdown code
      while IFS= read -r f; do printf -- '- `%s`\n' "$f"; done <<<"$bad"
      printf '\nVERDICT: REJECT\n'
    } >.factory/review.md
    printf '\n✗ scope check: only %s may change. Out of scope:\n%s\n' "$SCOPE" "$bad" >&2
    return 1
  fi
  emit scope after="$1" ok=true files="$changed"
}

code_fingerprint() {  # everything the PR would ship, new files included
  git add -N .
  git -c core.quotepath=off diff --no-renames --binary "$FACTORY_BASE" | git hash-object --stdin
}

# Last line that says something (not blank, not a --- rule or a code fence), normalised.
verdict_is_approve() {
  local last
  last="$(tr -d '\r' <.factory/review.md | grep -vE '^[[:space:]]*(-{3,}|`{3,}.*)?[[:space:]]*$' | tail -n 1 \
    | tr -d '*`_#> \t' | tr '[:lower:]' '[:upper:]' | sed 's/\.$//')"
  [[ "$last" == "VERDICT:APPROVE" ]]
}

# ═════════════════════════════════════════════════════════════════════════════════════════════
# MACHINERY — ending a run, timeouts, totals, the readable live output
# ═════════════════════════════════════════════════════════════════════════════════════════════

commit_run() {
  git add -A
  git -c core.hooksPath=/dev/null commit -q --no-verify -m "feat: ${ISSUE_TITLE} (#${ISSUE})" \
    -m "Built by factory.sh from issue #${ISSUE}."
}

# end_run <APPROVE|REJECT>: record the verdict, then commit (rehearsal) or open a PR.
end_run() {
  local verdict="$1" result
  if [[ "$verdict" == "REJECT" && -z "$STOPPED_BY" ]]; then STOPPED_BY="review"; fi
  emit verdict value="$verdict"
  if [[ -n "${FACTORY_NO_PUSH:-}" ]]; then
    commit_run
    result="committed"
    [[ "$verdict" == "APPROVE" ]] || result="rejected"
    printf '\nFACTORY_NO_PUSH set: %s run committed on %s, not pushed.\n' "$verdict" "$BRANCH"
    finish_run result="$result" verdict="$verdict" stopped_by="$STOPPED_BY" turns="$TOTAL_TURNS" cost="$TOTAL_COST"
  else
    printf '\n══ opening the PR on %s (a human decides; nothing is merged) ══\n' "$UPSTREAM"
    open_pr "$verdict"
  fi
  back_to_main
  [[ "$verdict" == "APPROVE" ]] || exit 1
}

back_to_main() {  # the next change belongs on main, where the next run starts
  git checkout -q main
  printf 'Now back on main: commit your next change here, then ./factory.sh <issue> again.\n'
}

# park_run: when a run stops early, keep its files on the run branch and leave main clean.
park_run() {
  [[ -n "$BRANCH" && "$(git branch --show-current 2>/dev/null)" == "$BRANCH" ]] || return 0
  git add -A >/dev/null 2>&1 || return 0
  if ! git diff --cached --quiet; then
    git -c core.hooksPath=/dev/null commit -q --no-verify -m "stopped run for #${ISSUE}" >/dev/null 2>&1 || return 0
  fi
  git checkout -q main 2>/dev/null || return 0
  printf 'Back on main, clean. What this run did so far is kept on branch %s.\n' "$BRANCH" >&2
}

timeout_cmd() {  # prints the timeout wrapper for this machine, if any
  if command -v gtimeout >/dev/null; then echo gtimeout; elif command -v timeout >/dev/null; then echo timeout; fi
}

# Another Claude Code session may be updating the shared claude binary right now (it disappears
# for a second or two during the swap). Wait up to 60 s for it to come back instead of crashing.
wait_for_claude() {
  local waited=0
  while hash -r && ! command -v claude >/dev/null; do
    ((waited++ < 60)) || die "claude is not on PATH (a Claude Code update still running? try 'claude --version')"
    ((waited > 1)) || printf '  … claude is being updated, waiting for it\n'
    sleep 1
  done
}

add_totals() {  # add a phase's turns and cost from its result line; leaves that phase's own in PHASE_*
  local turns cost
  turns="$(jq -rs '[.[] | select(.type == "result")] | last | .num_turns // 0' "$1")"
  cost="$(jq -rs '[.[] | select(.type == "result")] | last | .total_cost_usd // 0' "$1")"
  TOTAL_TURNS=$((TOTAL_TURNS + turns))
  PHASE_TURNS="$turns" PHASE_COST="$cost"
  PHASE_SECONDS="$(jq -rs '[.[] | select(.type == "result")] | last | ((.duration_ms // 0) / 1000 | round)' "$1")"
  TOTAL_COST="$(jq -n --argjson a "$TOTAL_COST" --argjson b "$cost" '(($a + $b) * 10000 | round) / 10000')"
}

# Turns the stream-json log into one readable line per action.
# shellcheck disable=SC2016  # $root is a jq variable
FILTER='
def short: tostring | ltrimstr($root) | gsub("\\s+"; " ") | if length > 110 then .[0:110] + "…" else . end;
if .type == "assistant" then
  .message.content[]?
  | if .type == "tool_use" then
      "  → \(.name)  \((.input.command // .input.file_path // .input.pattern // .input.path // "") | short)"
    elif .type == "text" and (.text | length) > 0 then
      "\n\(.text)\n"
    else empty end
elif .type == "user" then
  .message.content
  | if type == "array" then .[] else empty end
  | select(type == "object" and .type == "tool_result" and .is_error == true)
  | "  ✗ \(.content | if type == "array" then map(.text? // "") | join(" ") else . end | short)"
elif .type == "result" then
  "  ✓ \(.subtype) · \(.num_turns) turns · \(.duration_ms / 1000 | floor)s · $\((.total_cost_usd // 0) * 100 | round / 100)"
else empty end'

main
