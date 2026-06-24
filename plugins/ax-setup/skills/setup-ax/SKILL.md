---
name: setup-ax
description: >-
  Unified entry point for setting up AX measurement on Claude Code. Asks one
  question — is this PC a client (sends session transcripts), the server
  (receives them), or both (local testing) — then ensures the right plugin(s)
  are installed and runs their install skills in the correct order (server
  first, then the client pointed at it). A thin orchestrator: it installs no
  runtime of its own and delegates to install-ax-server / install-ax-monitor.
  Use on /setup-ax or when the user is unsure whether to install the client or
  the server, or wants a guided one-stop AX setup.
metadata:
  author: panicdna
  version: 1.0.0
  category: setup
  tags: [setup, orchestrator, claude-code, measurement, ax, entry-point]
---

# Setup AX measurement (unified entry point)

AX measurement has two halves that meet at `<host>:<port>/v1/sessions`:

- **client** (`ax-monitor` plugin) — a `SessionEnd`/`Stop` hook that POSTs each
  session transcript. Installed by `install-ax-monitor`.
- **server** (`ax-monitor-server` plugin) — the stdlib retail server that
  receives, captures, and (optionally) summarizes. Installed by
  `install-ax-server`.

They are **independent** — a PC can be one, the other, or both. This skill picks
the right halves for this PC and runs their installers in the right order. It
**does not** reimplement them; it delegates.

> Constraint: this skill cannot run `/plugin install` for you (that's a built-in
> interactive Claude Code command). For any half whose plugin isn't installed
> yet, it will tell you the exact `/plugin install` line to type, then continue.

## Step 1 — Pick this PC's role

Use `AskUserQuestion` (single-select):

**What is this PC's role in AX measurement?**

- "Client — I use `claude` here; send my sessions" — installs the hook only.
- "Server — this PC receives/stores sessions" — installs the `:14200` server only.
- "Both — local testing on one PC" — installs the server, then the client
  pointed at `localhost`.

Map the answer to the ordered list of halves to set up:

| Role   | Halves (in install order)              |
| ------ | -------------------------------------- |
| Client | `client`                               |
| Server | `server`                               |
| Both   | `server`, then `client`                |

Server goes first for "Both" so the client can target the port the server was
just configured with.

## Step 2 — Ensure the needed plugin(s) are installed

For each half, the plugin and its install skill are:

| Half   | Plugin name         | Install skill / command |
| ------ | ------------------- | ----------------------- |
| client | `ax-monitor`        | `/install-ax-monitor`   |
| server | `ax-monitor-server` | `/install-ax-server`    |

Detect whether each needed plugin is already installed (cached locally):

```bash
# Replace <plugin> with ax-monitor and/or ax-monitor-server as needed.
for p in <plugins-for-this-role>; do
  if ls -d ~/.claude/plugins/cache/*/"$p"/*/ >/dev/null 2>&1; then
    echo "INSTALLED $p"
  else
    echo "MISSING   $p"
  fi
done
```

If the marketplace itself is missing entirely (no `~/.claude/plugins/cache/*/`),
tell the user to run `/plugin marketplace add panicdna/ax-monitor` first.

For every `MISSING` plugin, tell the user to run the matching line(s), then
**wait** for them to confirm (these are built-in commands you can't run):

```
/plugin install ax-monitor          # client
/plugin install ax-monitor-server   # server
```

After they confirm, they may need `/reload-plugins` (or reopening `/hooks`) for
the new skills to register this session. Re-detect to confirm `INSTALLED`
before proceeding. Do not continue to Step 3 for a half whose plugin is still
missing.

## Step 3 — Run the installer(s), in order

For each half (server before client when role is Both), invoke its install
skill. Invoke them **one at a time** and let each finish its interactive prompts
before starting the next:

- server → invoke the `install-ax-server` skill (a.k.a. `ax-monitor-server:install-ax-server`).
- client → invoke the `install-ax-monitor` skill (a.k.a. `ax-monitor:install-ax-monitor`).

If you (the model) cannot invoke a skill directly, instruct the user to run the
slash command (`/install-ax-server`, then `/install-ax-monitor`) in that order.

**Threading the URL for "Both":** the server installer asks for a bind IP and
port (default 14200). Note the chosen port. When the client installer then asks
for the measurement server URL, choose "Deployed AX server" and enter
`http://localhost:<that-port>/v1/sessions` (localhost, since it's the same PC).

## Step 4 — Hand-off

Summarize what was set up for this PC's role:

- **Server installed:** dashboard at `http://localhost:<port>/`, manage with
  `~/.claude/ax-monitor-server/ax-server.sh {start|stop|restart|status}`, logs at
  `~/.claude/ax-server.log`. Give remote clients `http://<this-pc-lan-ip>:<port>/v1/sessions`.
- **Client installed:** open `/hooks` once to reload (takes effect next session);
  watch `~/.claude/ax-hook.log` for `result http=200`.
- **Both:** the hook here targets the local server; one PC is the full loop.

Point to the per-half skills for changes later: `/install-ax-server` and
`/install-ax-monitor` are both idempotent (re-run to reconfigure), and
`/uninstall-ax-server` / `/uninstall-ax-monitor` remove each half.

## Notes for the model

- This skill is **pure orchestration** — it copies no files and writes no
  settings itself. All real work happens inside the delegated install skills.
- Never claim a plugin is installed without the Step 2 cache check passing.
- Respect ordering for "Both": server first (so its port is known), client
  second (pointed at `localhost:<port>`).
- If the user already told you the role in their message (e.g. "set up the
  server"), skip the Step 1 question and proceed with that role.
- Detection globs `~/.claude/plugins/cache/*/<plugin>/*/` so it works regardless
  of the local marketplace alias.
