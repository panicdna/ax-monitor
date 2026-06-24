---
name: uninstall-ax-server
description: >-
  Stop and remove the ax-monitor-server installed by /install-ax-server. Stops
  the nohup-managed daemon via its launcher, then optionally deletes the
  installed runtime (~/.claude/ax-monitor-server/), the server log
  (~/.claude/ax-server.log), and the captured sessions. Touches nothing else.
  Use on /uninstall-ax-server or when the user wants to shut down / remove the
  AX measurement server.
metadata:
  author: panicdna
  version: 1.0.0
  category: server
  tags: [server, claude-code, measurement, ax, uninstall, cleanup]
---

# Uninstall ax-monitor-server

Stop the retail server daemon and clean up. Only the ax-monitor-server install
directory and its process are touched — nothing else.

## Steps

### 1. Detect what's installed / running

```bash
if [ -x ~/.claude/ax-monitor-server/ax-server.sh ]; then
  ~/.claude/ax-monitor-server/ax-server.sh status 2>/dev/null || true
  echo "INSTALLED"
else
  echo "(no ax-monitor-server install found)"
fi
```

If not installed, tell the user "nothing to uninstall" and stop.

### 2. Stop the daemon

```bash
~/.claude/ax-monitor-server/ax-server.sh stop 2>/dev/null || true
# Backstop: kill any lingering process started from the install dir.
pkill -f "$HOME/.claude/ax-monitor-server/main.py" 2>/dev/null || true
echo "✓ stopped"
```

### 3. Confirm it's down

```bash
PORT="$(cat ~/.claude/ax-monitor-server/ax-server.pid 2>/dev/null >/dev/null; echo "${AX_SERVER_PORT:-14200}")"
if curl -fsS --noproxy '*' -m3 "http://localhost:$PORT/health" >/dev/null 2>&1; then
  echo "✗ something still answers on :$PORT — another server? investigate before deleting"
else
  echo "✓ port :$PORT no longer answering"
fi
```

If something still answers, it may be a *different* server on that port — flag
it to the user before deleting files.

### 4. Optional file cleanup

Ask the user whether to also delete the installed runtime, log, and captures
(default: keep — **captures hold raw session content** that may be wanted).
Offer two levels:

```bash
# Level A — remove runtime + log, KEEP captures:
find ~/.claude/ax-monitor-server -mindepth 1 -maxdepth 1 ! -name captures -exec rm -rf {} +
rm -f ~/.claude/ax-server.log
echo "✓ removed runtime + log, kept captures/"

# Level B — remove everything including captures:
# rm -rf ~/.claude/ax-monitor-server ~/.claude/ax-server.log
# echo "✓ removed runtime, log, and all captures"
```

### 5. Hand-off

Tell the user:

> Server stopped and removed. It was nohup-managed (not systemd) so there's no
> service unit to clean up. Clients still pointed at this URL will get
> connection-refused — their hook logs `http=000` but never blocks the session.
>
> Reinstall any time with `/install-ax-server`. (If you also want the plugin
> package gone: `/plugin uninstall ax-monitor-server` — run this uninstall skill
> first so the daemon is actually stopped.)

## Notes for the model

- The launcher's `stop` reads the PID file; the `pkill -f .../main.py` backstop
  catches an orphan whose PID file was lost. Both are scoped to the install dir.
- Default to **keeping** `captures/` unless the user explicitly opts into
  Level B — raw session content is not trivially recoverable once deleted.
- If Step 3 still shows a live `/health`, do not delete blindly: it may be an
  unrelated server (or the client plugin's `:14210` local-verifier).
