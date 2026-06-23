---
name: uninstall-ax-monitor
description: >-
  Remove the ax-monitor hooks installed by /install-ax-monitor. Strips hook
  entries referencing ax-monitor/ax_session_end from ~/.claude/settings.json
  (across SessionEnd and Stop), and optionally deletes the installed runtime
  (~/.claude/ax-monitor/), the call log, and the turn-counter state. Preserves
  all unrelated hooks and settings. Use on /uninstall-ax-monitor or when the
  user wants to disable AX measurement.
metadata:
  author: panicdna
  version: 1.0.0
  category: hooks
  tags: [hooks, claude-code, measurement, ax, uninstall, cleanup]
---

# Uninstall ax-monitor

Remove ax-monitor hooks and clean up. Preserves all unrelated hooks and
settings — only entries whose command references `ax-monitor/ax_session_end`
are removed.

## Steps

### 1. Detect what will be removed (for the user's confirmation)

```bash
echo "=== Existing ax-monitor hooks ==="
jq '
  [ .hooks // {} | to_entries[]
    | { event: .key,
        cmds: (.value | map(.hooks[] | select(.command | test("ax-monitor/ax_session_end")) | .command)) }
    | select(.cmds | length > 0) ]
' ~/.claude/settings.json 2>/dev/null || echo "(no settings.json)"
```

If nothing is listed, tell the user "nothing to uninstall" and skip to step 4
(file cleanup question).

### 2. Strip our hooks from settings.json

Filter out any hook entry whose command contains `ax-monitor/ax_session_end`.
Collapse emptied parent arrays / keys so no structural garbage is left behind.

```bash
jq '
  if .hooks then
    .hooks |= (
      to_entries
      | map(
          .value |= (
            map(.hooks |= map(select(.command | test("ax-monitor/ax_session_end") | not)))
            | map(select(.hooks | length > 0))
          )
        )
      | map(select(.value | length > 0))
      | from_entries
    )
    | if (.hooks | length == 0) then del(.hooks) else . end
  else . end
' ~/.claude/settings.json > /tmp/ax.settings.new && mv /tmp/ax.settings.new ~/.claude/settings.json
```

### 3. Validate JSON

```bash
jq empty ~/.claude/settings.json && echo "✓ valid"
jq -e '.. | .command? // empty | select(test("ax-monitor/ax_session_end"))' ~/.claude/settings.json >/dev/null 2>&1 \
  && echo "✗ an ax-monitor command still lingers — investigate" \
  || echo "✓ all ax-monitor hooks removed"
```

### 4. Optional file cleanup

Ask the user whether to also delete the installed runtime and logs (default:
keep). If they confirm:

```bash
rm -rf ~/.claude/ax-monitor
rm -f  ~/.claude/ax-hook.log
rm -rf ~/.claude/ax-hook-state
echo "✓ removed runtime, call log, and turn-counter state"
```

### 5. Hand-off

Tell the user:

> Uninstalled. Open `/hooks` once to reload settings — the running session
> still caches the removed hooks until you reload. After reload, no transcript
> is sent.
>
> Reinstall any time with `/install-ax-monitor`. (If you also want the plugin
> package gone: `/plugin uninstall ax-monitor` — but run this uninstall skill
> first so no ghost hook is left behind.)

## Notes for the model

- This skill never touches settings unrelated to ax-monitor.
- The `jq` filter uses `test("ax-monitor/ax_session_end")` as the detection
  signature. If the pre-detection step shows hooks the user doesn't recognize,
  flag it before removing.
- Default to **keeping** the runtime/logs unless the user asks to delete — the
  call log (`~/.claude/ax-hook.log`) may be useful history.
