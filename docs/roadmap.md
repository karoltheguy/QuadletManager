# Roadmap

This is the project owner's running list of ideas for QuadletManager, with priority and feasibility notes added by AI to help sort and scope them.

Priority: **P0** (next up) · **P1** (planned) · **P2** (nice to have, no rush).

> Items already tracked as GitHub issues are cross-referenced.

## Monitor tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | Show total CPU + MEM usage per server | **P0** | Natural extension of the existing per-container stats poller (see `docs/ARCHITECTURE.md` monitoring section); mostly an aggregation plus a header stat, low risk. |
| 2 | Clicking a container in Monitor applies all the right filters so only that container's data shows, nothing else | **P1** | A filter-state change rather than a new view: selecting a container programmatically sets every relevant filter/dropdown to isolate it. Pairs with #3. |
| 3 | One-click "filter down to just this container" control, remembered across sessions | **P1** | A dedicated one-click affordance (not just clicking the container itself) that isolates a single container and persists the choice across tab switches and reloads. Natural to build alongside #2 since both share the same filter-state mechanism. |
| 4 | Favorite server in Monitor (default is first, shown with details) | **P1** | Needs a small persisted preference (per-user or per-browser). |
| 22 | Configurable refresh rate for server CPU/MEM polling | **P2** | Settings control for how often Monitor re-polls stats; pairs naturally with #23. |
| 23 | Show/hide server CPU/MEM info in Monitor tab | **P2** | Companion toggle to #1/#18: once aggregate CPU/MEM is added, let users hide it if they don't want it taking up space. |

## Overview tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 5 | Auto-width server dashboard (3-4 wide depending on screen width), plus a saved preference for a constant grid width and server order | **P1** | Two parts: (a) responsive auto-width behavior, which relates to open issue **#69 (Mobile-responsive layout for all views)**; (b) a persisted override so a fixed column count and server order can be pinned instead of relying on auto-width. Part (b) is effectively what #24 asks for as a settings-page control, so the two should be built together. |
| 6 | Unhealthy containers should visually spring into sight, impossible to miss | **P0** | About visual salience (e.g. a pulsing badge, glow, or attention animation) so a bad container state is immediately obvious without hunting for it, not a navigation/jump-to-section feature. |
| 18 | Show CPU/MEM usage per server next to server name in Overview | **P1** | Same data source as Monitor item #1: build the aggregation once, surface it in both places. |
| 24 | Settings/options to set grid preferences in Overview | **P1** | The UI surface for the persisted grid-width/order preference described in #5(b), same feature. |

## Containers tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 7 | Inspector doesn't use vertical space well | **P1** | Specifically vertical space, likely padding/sizing of the widget stack in the inspector panel. |
| 8 | Arrow to expand Terminal/Logs to full height | **P1** | Common "maximize pane" pattern; natural to build alongside #9 since both touch the same layout region. |
| 9 | Reduce spacing between Inspector and Editor | **P1** | Part of the same layout pass as #7/#8. |
| 10 | Expand/Collapse All button for server list | **P2** | Small quality-of-life, low urgency. |
| 11 | Reorder servers in Containers | **P2** | Needs a persisted order (per-user setting), likely the same mechanism as Monitor's favorite server (#4) and Overview's grid/order preference (#5, #24). Open question: should Containers' server order and Overview's server order be the same preference or independent ones? |
| 12 | Dim Start/Stop/Restart buttons in Inspector | **P2** | Pure CSS/styling tweak. |
| 13 | Unsaved-changes indicator for Editor | **P0** | ✅ Done — implemented as issue **#188** (dirty indicator, discard confirmation on file switch, beforeunload guard). |
| 15 | Visually group containers belonging to a pod | **P1** | Improves readability once server lists get busy; moderate UI work. |
| 16 | Lint/validate Editor content against systemd/Podman unit syntax | **P0** | Prevents shipping broken units to servers, the highest-value item in this tab. Could start simple (basic key/section validation) and grow from there. |
| 17 | Option to enable/disable the panel on the right side of the Editor | **P2, needs scoping** | The Editor already has an Inspector-collapse toggle (`inspector-expand-btn` / `toggleInspectorExpand()` in `static/main.js`). Needs a decision on whether this item describes that existing toggle or a distinct panel. |
| 19 | Import a docker-compose file (and docker run commands) into a Quadlet unit via the Editor | **P1** | [PodletJS](https://github.com/karoltheguy/PodletJS) already supports full compose parsing (multi-service, networks, volumes, healthchecks, `depends_on`) and docker-run parsing. Since it's a plain npm package and this repo already vendors browser JS the same way (`xterm`, `xterm-addon-fit` copied into `static/` via the `copy-assets` script), the cleanest path is to vendor PodletJS the same way and run the conversion entirely client-side in the Editor: paste/upload compose YAML or a docker-run command, generate the quadlet content, load it into Monaco. No server round-trip needed. |

## Cross-cutting / infrastructure

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 14 | Move to PostgreSQL for enterprise-grade / production-readiness (potential government use) | **P2, needs discussion** | Open issue **#173** proposes SQLite WAL mode plus `busy_timeout` as a lighter-weight fix, explicitly against an RDBMS migration unless the app goes multi-worker, and that's correct for raw performance. Targeting government/enterprise deployments changes the calculus beyond performance, though: WAL itself is not more crash-prone than the default journal mode (committed transactions are fsynced to the WAL file, so a container reboot alone doesn't lose committed work), but backup/restore procedures that capture only the main `.db` file and miss the `-wal`/`-shm` sidecar files can lose recently-committed transactions. That's a configuration/ops concern, not a reason by itself to switch databases. Where Postgres starts to matter for this kind of target is procurement and compliance: mature point-in-time recovery and backup tooling, row-level access control, network-level auth separate from the app, and multi-instance/HA support. Worth its own issue, distinct from #173, if government/enterprise deployment becomes a real target rather than a performance question. |
| 20 | Fix the row just beneath the Terminal/Logs button; its styling makes it look broken/empty | **P0** | Cheap visual bug, easy win, ship anytime. |
| 21 | Logo (top-left header and login page) | **P1** | No dependencies, but needs an actual asset before implementation. |
