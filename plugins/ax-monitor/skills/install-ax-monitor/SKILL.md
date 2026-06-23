---
name: install-ax-monitor
description: >-
  Install the ax-monitor measurement hook for Claude Code. Copies the bundled
  hook into ~/.claude/ax-monitor/ and merges a SessionEnd and/or Stop hook into
  ~/.claude/settings.json that POSTs each session transcript to an AX
  measurement server. Interactive — asks for the server URL, which event(s) to
  fire on, per-turn rows, and the user id. Idempotent (re-run to reconfigure)
  and isolated (only hooks referencing ax-monitor/ax_session_end are touched).
  Use on /install-ax-monitor or when the user wants to enable AX usage
  measurement / the session-transcript hook.
metadata:
  author: panicdna
  version: 1.0.0
  category: hooks
  tags: [hooks, claude-code, telemetry, measurement, ax]
---

# Install ax-monitor

Register a `SessionEnd` and/or `Stop` hook that ships the session transcript to
an AX measurement server. The user keeps using `claude` normally — sending is
synchronous but the server answers on receipt (so no perceptible delay), and a
failure/timeout never blocks session exit.

`${CLAUDE_PLUGIN_ROOT}` is the absolute path to this plugin, injected by Claude
Code. The bundled runtime lives at `${CLAUDE_PLUGIN_ROOT}/runtime/`.

## Pre-flight checks

Run all in one Bash call:

```bash
echo "=== jq ==="; command -v jq || echo MISSING
echo "=== curl ==="; command -v curl || echo MISSING
echo "=== runtime ==="; ls "${CLAUDE_PLUGIN_ROOT}/runtime/ax_session_end.sh" 2>/dev/null || echo "runtime MISSING"
echo "=== settings ==="; ls ~/.claude/settings.json 2>/dev/null || echo "(no settings.json yet — will create)"
```

If `jq` or `curl` is MISSING, stop and tell the user to install them
(`! sudo apt install -y jq curl`) then retry `/install-ax-monitor`.

## Detect existing installation

```bash
jq -e '.. | .command? // empty | select(test("ax-monitor/ax_session_end"))' ~/.claude/settings.json >/dev/null 2>&1 && echo "EXISTS" || echo "FRESH"
```

If EXISTS, tell the user it's already installed and ask whether to reconfigure
(re-running replaces the ax-monitor hooks in place). If they decline, exit.

## Gather parameters

Unless the user already specified them, use `AskUserQuestion` (each a separate
single-select question):

**1. Measurement server URL** (`AX_SUMMARIZER_URL`)

- "Local verifier — http://localhost:14210/v1/sessions" — recommended for
  testing (run the bundled `runtime/local-verifier`, see below).
- "Deployed AX server" — then ask for the full URL ending in `/v1/sessions`
  (e.g. `http://ahn-vatar.internal/v1/sessions`).

**2. When to fire** (event)

- "SessionEnd — once when the session ends" — recommended (one card per session).
- "Stop — every turn (each command)" — more granular; with per-turn rows below
  you get one row per command.
- "Both" — Stop per turn + a final SessionEnd snapshot.

**3. Per-turn rows** (`AX_PER_TURN`, only meaningful with Stop)

- "Off — one row per session, updated each turn" — recommended default.
- "On — a new row per command (session_id gets a -tNNN suffix)".

**4. User id** (`AX_USER_ID`)

- "System user (`whoami`)" — recommended for local testing.
- "Custom (e.g. corporate / Knox mail)" — then ask for the value.

## Step 1 — Copy runtime into place

```bash
INSTALL_DIR="$HOME/.claude/ax-monitor"
mkdir -p "$INSTALL_DIR"
cp -r "${CLAUDE_PLUGIN_ROOT}/runtime/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/ax_session_end.sh"
ls -l "$INSTALL_DIR/ax_session_end.sh" && echo "✓ runtime installed"
```

## Step 2 — Connectivity check (best-effort)

Derive the server base from the chosen URL and probe `/health`. The server may
legitimately be down (the user starts it later) — so this only **warns**, it
does not block.

```bash
URL='<AX_SUMMARIZER_URL>'
BASE="${URL%/v1/sessions}"
if curl -fsS --noproxy '*' -m3 "$BASE/health" >/dev/null 2>&1; then
  echo "✓ server reachable: $BASE"
else
  echo "⚠ server not reachable at $BASE — hook will still be installed, but"
  echo "  data won't land until the server is up. For the bundled local verifier:"
  echo "    python ~/.claude/ax-monitor/local-verifier/main.py --summarize"
fi
```

## Step 3 — Compose hook command

Build the command string from the chosen parameters. `~` expands (the hook runs
via shell); env vars are written as literal values. Include `AX_PER_TURN=1`
only if the user chose per-turn rows.

```bash
# Example (Stop + per-turn + custom user):
# AX_PER_TURN=1 AX_SUMMARIZER_URL='http://localhost:14210/v1/sessions' AX_USER_ID='hong@samsung.com' ~/.claude/ax-monitor/ax_session_end.sh
HOOK_CMD="AX_SUMMARIZER_URL='<URL>' AX_USER_ID='<UID>' ~/.claude/ax-monitor/ax_session_end.sh"
# prepend "AX_PER_TURN=1 " if per-turn chosen
```

Every command contains the path `ax-monitor/ax_session_end` — that is the
detection signature for idempotent re-install and clean uninstall.

## Step 4 — Test fire before writing settings

If the server was reachable in Step 2, prove the path end-to-end with a tiny
synthetic transcript (a new throwaway session id). Skip if the server is down.

```bash
TMP=$(mktemp)
printf '%s\n' '{"type":"user","message":{"content":"ax-monitor install test"}}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"ok"}]}}' > "$TMP"
printf '{"session_id":"ax-monitor-install-test","transcript_path":"%s","cwd":"%s"}' "$TMP" "$PWD" \
  | env <the same env vars> bash "$HOME/.claude/ax-monitor/ax_session_end.sh"
tail -2 ~/.claude/ax-hook.log   # expect: result ... http=200
rm -f "$TMP"
```

If the result line shows `http=200`, proceed. If `http=000`/non-200, report it
(server down / wrong URL) and ask whether to install the hook anyway.

## Step 5 — Merge into ~/.claude/settings.json

Create `{}` if missing, then merge the chosen event(s). Run the jq block **once
per chosen event** (`SessionEnd` and/or `Stop`), replacing any existing
ax-monitor hook for that event.

```bash
[ -f ~/.claude/settings.json ] || echo '{}' > ~/.claude/settings.json

EVENT='SessionEnd'   # or 'Stop'
jq --arg cmd "$HOOK_CMD" --arg ev "$EVENT" '
  .hooks //= {}
  | .hooks[$ev] = (
      (.hooks[$ev] // [])
      | map(.hooks |= map(select(.command | test("ax-monitor/ax_session_end") | not)))
      | map(select(.hooks | length > 0))
    ) + [{"hooks": [{"type": "command", "command": $cmd}]}]
' ~/.claude/settings.json > /tmp/ax.settings.new && mv /tmp/ax.settings.new ~/.claude/settings.json
```

## Step 6 — Validate

```bash
jq empty ~/.claude/settings.json && echo "✓ JSON valid"
jq -e '.. | .command? // empty | select(test("ax-monitor/ax_session_end"))' ~/.claude/settings.json >/dev/null && echo "✓ ax-monitor hook present"
```

## Step 7 — Hand-off

Tell the user:

> Installed. Open `/hooks` once to reload settings (Claude Code caches
> settings.json at session start, so this takes effect from your **next**
> session — or after a reload). Then work normally; on each chosen event the
> session transcript is sent to the measurement server.
>
> - Watch invocations: `tail -f ~/.claude/ax-hook.log` (`invoked` / `send` /
>   `result http=200`).
> - Local target: `python ~/.claude/ax-monitor/local-verifier/main.py --summarize`
>   (optionally `--forward <deployed-url>` to relay to a real backend).
> - Opt out for a shell: `export AX_MEASUREMENT_OFF=1`.
> - Remove: `/uninstall-ax-monitor`.

## Notes for the model

- The hook command must be a single line in the JSON `command` field. Don't
  pretty-print it across lines.
- Detection signature is the path substring `ax-monitor/ax_session_end`. It is
  unique enough not to false-match unrelated hooks.
- Keep `~/.claude/ax-monitor/ax_session_end.sh` unquoted in the command so the
  tilde expands (the hook runs via shell). Quote the env **values**.
- `Stop` fires every turn but the server keys rows by session_id; without
  `AX_PER_TURN=1` the same row updates each turn (one card per session). With
  it, each turn becomes a new `-tNNN` row.
- The bundled `runtime/local-verifier/` is a single-file stdlib server — no
  external deps. It captures raw transcript + headers, prints a
  production-equivalent breakdown, optionally summarizes (OpenAI-compatible,
  stub fallback), and can `--forward` to a real backend.
