---
name: install-ax-server
description: >-
  Install the ax-monitor measurement retail server on this PC. Copies the
  bundled stdlib server into ~/.claude/ax-monitor-server/ and starts it as a
  nohup-managed background daemon that receives the raw session transcript the
  ax-monitor hook POSTs to /v1/sessions (capture + deterministic breakdown +
  optional summarize/forward + read-only dashboard). Interactive — asks for the
  bind IP, the port (default 14200), and whether to enable summarize/forward.
  Idempotent (re-run to reconfigure; restarts in place) and isolated (only the
  ax-monitor-server install dir and its PID are touched). Use on
  /install-ax-server or when the user wants to stand up the AX measurement
  server / the :14200 receiver + dashboard.
metadata:
  author: panicdna
  version: 1.0.0
  category: server
  tags: [server, claude-code, telemetry, measurement, ax, dashboard]
---

# Install ax-monitor-server

Stand up the **receiving end** of AX measurement: a single-file stdlib
`http.server` that captures the raw transcript the `ax-monitor` hook sends,
prints a deterministic breakdown, optionally summarizes (OpenAI-compatible) and
forwards upstream, and serves a read-only dashboard at `/`. It runs as a
**nohup-managed background daemon** (no systemd needed) with a configurable
bind IP and **port (default 14200)**.

`${CLAUDE_PLUGIN_ROOT}` is the absolute path to this plugin, injected by Claude
Code. The bundled runtime lives at `${CLAUDE_PLUGIN_ROOT}/runtime/`.

This is the server side. The client hook is installed separately by
`/install-ax-monitor`; point that hook's `AX_SUMMARIZER_URL` at this server's
`http://<this-pc-ip>:<port>/v1/sessions`.

## Pre-flight checks

Run all in one Bash call:

```bash
echo "=== python3 ==="; command -v python3 && python3 --version || echo MISSING
echo "=== runtime ==="; ls "${CLAUDE_PLUGIN_ROOT}/runtime/main.py" 2>/dev/null || echo "runtime MISSING"
echo "=== launcher ==="; ls "${CLAUDE_PLUGIN_ROOT}/runtime/ax-server.sh" 2>/dev/null || echo "launcher MISSING"
echo "=== existing install ==="; ls ~/.claude/ax-monitor-server/ax-server.sh 2>/dev/null && echo EXISTS || echo FRESH
echo "=== curl (optional) ==="; command -v curl || echo "(no curl — health probe skipped)"
```

If `python3` is MISSING, stop and tell the user to install it
(`! sudo apt install -y python3`) then retry `/install-ax-server`. Python ≥ 3.10
is required (the server uses `X | Y` type unions). `curl` is optional (only the
health probe needs it). The server itself has **zero pip dependencies** —
stdlib only.

## Detect existing installation

```bash
if [ -x ~/.claude/ax-monitor-server/ax-server.sh ]; then
  ~/.claude/ax-monitor-server/ax-server.sh status 2>/dev/null || true
  echo "EXISTS"
else
  echo "FRESH"
fi
```

If EXISTS, tell the user it's already installed and ask whether to reconfigure
(re-running copies the latest runtime and **restarts** the server with the new
host/port). If they decline, exit.

## Gather parameters

Unless the user already specified them, use `AskUserQuestion` (each a separate
single-select question):

**1. Bind IP** (`AX_SERVER_HOST`) — which interface the server listens on

- "All interfaces — 0.0.0.0" — recommended. Reachable from other PCs on the
  LAN; clients use this PC's LAN IP. (We detect and show that IP at the end.)
- "Loopback only — 127.0.0.1" — only this PC can reach it (single-machine test).
- "Specific IP" — then ask for the exact address to bind (must be an IP this
  PC actually holds).

**2. Port** (`AX_SERVER_PORT`)

- "14200 (default)" — recommended; matches the hook's documented target.
- "Custom" — then ask for the port number (1–65535). If the client hook is
  already installed, its `AX_SUMMARIZER_URL` must use the same port.

**3. Summarize** (`AX_SERVER_SUMMARIZE`)

- "Off — capture + breakdown only" — recommended default; pure receiver.
- "On — also run the summarize path" — adds `--summarize`. With no `LLM_BASE_URL`
  in the environment it falls back to a deterministic stub (no LLM needed).

**4. Forward upstream** (`AX_SERVER_FORWARD`)

- "Off — terminal server" — recommended. This server is the final destination.
- "On — relay raw POST upstream" — then ask for the upstream URL ending in
  `/v1/sessions` (the same raw body is forwarded there too).

## Step 1 — Copy runtime into place

```bash
INSTALL_DIR="$HOME/.claude/ax-monitor-server"
mkdir -p "$INSTALL_DIR"
cp -r "${CLAUDE_PLUGIN_ROOT}/runtime/." "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/ax-server.sh"
ls -l "$INSTALL_DIR/ax-server.sh" "$INSTALL_DIR/main.py" && echo "✓ runtime installed"
```

## Step 2 — Free-port check

The chosen port must be free (or held by a previous instance of *this* server,
which Step 4 restarts). Warn — don't hard-fail — since a stale instance is fine.

```bash
PORT='<AX_SERVER_PORT>'
if (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -q "[:.]$PORT[[:space:]]"; then
  echo "⚠ port $PORT already in use — if it's a previous ax-monitor-server it will be"
  echo "  restarted in Step 4; otherwise pick another port (re-run /install-ax-server)."
else
  echo "✓ port $PORT is free"
fi
```

## Step 3 — Write the launcher config file

Persist the chosen parameters to `~/.claude/ax-monitor-server/ax-server.env`.
The launcher sources this on every call, so `start`/`stop`/`restart`/`status`
all use the same host/port without an env prefix. Write `AX_SERVER_SUMMARIZE=1`
only if summarize was chosen, and `AX_SERVER_FORWARD=...` only if forwarding —
substitute the gathered values for `<HOST>` / `<PORT>` / `<URL>`.

```bash
ENVFILE="$HOME/.claude/ax-monitor-server/ax-server.env"
{
  echo "AX_SERVER_HOST='<HOST>'"
  echo "AX_SERVER_PORT='<PORT>'"
  # echo "AX_SERVER_SUMMARIZE=1"          # only if summarize chosen
  # echo "AX_SERVER_FORWARD='<URL>'"      # only if forwarding chosen
} > "$ENVFILE"
cat "$ENVFILE" && echo "✓ config written"
```

## Step 4 — Start (or restart) the daemon

Use `restart` so a re-install cleanly replaces any running instance. No env
prefix needed — the launcher reads `ax-server.env` from Step 3.

```bash
~/.claude/ax-monitor-server/ax-server.sh restart
```

Expect `✓ 기동됨 (pid=...)`. If it says `✗ 기동 직후 종료됨`, show the user
`tail -20 ~/.claude/ax-server.log` (usually a port clash or a bad forward URL).

## Step 5 — Health check + advertise the URL clients should use

```bash
PORT='<AX_SERVER_PORT>'
curl -fsS --noproxy '*' -m3 "http://localhost:$PORT/health" && echo "  ← ✓ /health ok"
echo "이 PC 의 LAN IP (클라이언트가 쓸 주소):"
hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]' | sed "s#\$#:$PORT/v1/sessions#" | sed 's#^#  http://#'
```

If bound to `0.0.0.0`, any of the listed `http://<ip>:<port>/v1/sessions` URLs
works for remote clients; for `127.0.0.1` only `http://localhost:<port>/...`
works (same machine). Tell the user to set the hook's `AX_SUMMARIZER_URL` to the
matching URL (re-run `/install-ax-monitor` to change it).

## Step 6 — Hand-off

Tell the user:

> Server installed and running. It does **not** auto-start on reboot (nohup,
> not systemd) — after a reboot run `~/.claude/ax-monitor-server/ax-server.sh
> start` again (or add that line to your shell profile / a cron `@reboot`).
>
> - Dashboard: `http://localhost:<port>/` (read-only; polls captured sessions).
> - Manage: `~/.claude/ax-monitor-server/ax-server.sh {start|stop|restart|status}`.
> - Server log: `tail -f ~/.claude/ax-server.log` (the per-request breakdown
>   report prints here).
> - Captures: `~/.claude/ax-monitor-server/captures/*.{jsonl,meta.json}` (raw
>   session content — keep private).
> - Point clients here: set the hook's `AX_SUMMARIZER_URL` to
>   `http://<this-pc-ip>:<port>/v1/sessions` via `/install-ax-monitor`.
> - Remove: `/uninstall-ax-server`.

## Notes for the model

- Port **default is 14200** — the documented target the `ax-monitor` hook
  expects. Only deviate if the user asks; if they do, remind them the hook's
  `AX_SUMMARIZER_URL` must use the same port.
- "Bind IP" is the *listening* interface, not the address clients type. For LAN
  reach, bind `0.0.0.0` and give clients this PC's LAN IP (Step 5 prints it).
- The server is stdlib-only (Python ≥ 3.10, zero pip deps). Do not add
  dependencies or suggest `pip install`.
- The launcher manages a PID file at `~/.claude/ax-monitor-server/ax-server.pid`
  and is idempotent: `start` is a no-op if already running; `restart` replaces
  it. Re-running this skill copies the latest runtime then `restart`s.
- Config lives in `~/.claude/ax-monitor-server/ax-server.env` (Step 3); the
  launcher sources it every call, so `status`/`stop`/`restart` need no env
  prefix. To change host/port/summarize later, edit that file and run
  `ax-server.sh restart` (or just re-run this skill).
- This is the *server*. The *client* hook is `/install-ax-monitor` in the sibling
  `ax-monitor` plugin — they meet at `<host>:<port>/v1/sessions`.
