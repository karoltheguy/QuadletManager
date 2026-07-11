# Roadmap

Working list of planned improvements, organized by area with priority and rationale.
Priority: **P0** (do next) · **P1** (soon) · **P2** (nice to have, no rush).

> Note: items already tracked as GitHub issues are cross-referenced.

## Monitor tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 1 | Show total CPU + MEM usage per server | **P0** | Natural extension of the existing per-container stats poller (see `docs/ARCHITECTURE.md` monitoring section); mostly an aggregation + a header stat, low risk. |
| 2 | Clicking a container in Monitor applies all the right filters so *only* that container's data shows — nothing else | **P1** | This is a filter-state change, not a new view: selecting a container programmatically sets every relevant filter/dropdown to isolate it. Pairs with #3. |
| 3 | One-click "filter down to just this container" control, and remember the choice | **P1** | Builds on #2 — a dedicated one-click affordance (not just clicking the container itself) that isolates a single container and persists the choice (survive tab switch / reload). Do #2 and #3 together since they're the same underlying filter-state mechanism. |
| 4 | Favorite server in Monitor (default = first, show details) | **P1** | Needs a small persisted preference (per-user or per-browser). Decide storage before starting — see chat discussion on localStorage vs. server-side. |
| 22 | Configurable refresh rate for server CPU/MEM polling | **P2** | Settings control for how often Monitor re-polls stats; pairs naturally with #23. |
| 23 | Show/hide server CPU/MEM info in Monitor tab | **P2** | Companion toggle to #1/#18 — once aggregate CPU/MEM is added, let users hide it if they don't want it taking up space. |

## Overview tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 5 | Auto-width server dashboard (3-4 wide depending on screen width), plus a saved preference for a constant grid width and server order | **P1** | Two parts: (a) responsive auto-width behavior — relates to open issue **#69 (Mobile-responsive layout for all views)**; (b) a persisted override so a user can pin a fixed column count and server order instead of relying on auto-width. Part (b) is effectively what #24 asks for as a settings-page control, so build them together. |
| 6 | Unhealthy containers should visually spring into sight — impossible to miss | **P0** | Not a navigation/jump-to-section feature — this is about visual salience (e.g. a pulsing badge, glow, or attention animation) so a bad container state is immediately obvious without hunting for it. |
| 18 | Show CPU/MEM usage per server next to server name in Overview | **P1** | Same data source as Monitor item #1 — build the aggregation once, surface it in both places. |
| 24 | Settings/options to set grid preferences in Overview | **P1** | This is the UI surface for the persisted grid-width/order preference described in #5(b) — same feature, treat as one piece of work. |

## Containers tab

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 7 | Inspector doesn't use vertical space well | **P1** | Specifically vertical space (not just general layout) — likely padding/sizing of the widget stack in the inspector-panel. |
| 8 | Arrow to expand Terminal/Logs to full height | **P1** | Common "maximize pane" pattern; bundle with #9 since both touch the same layout region. |
| 9 | Reduce spacing between Inspector and Editor | **P1** | Bundle with #7/#8 as one layout pass. |
| 10 | Expand/Collapse All button for server list | **P2** | Small quality-of-life, low urgency. |
| 11 | Reorder servers in Containers | **P2** | Needs a persisted order (per-user setting) — decide storage model, likely same mechanism as Monitor favorite (#4) and Overview grid/order (#5, #24). Worth deciding whether Containers' server order and Overview's server order should be the same preference or independent ones. |
| 12 | Dim Start/Stop/Restart buttons in Inspector | **P2** | Pure CSS/styling tweak. |
| 13 | Unsaved-changes indicator for Editor | **P0** | Prevents real data loss (navigating away with unsaved quadlet edits) — this is a correctness/safety issue, not just polish. |
| 15 | Visually group containers belonging to a pod | **P1** | Improves readability once server lists get busy; moderate UI work. |
| 16 | Lint/validate Editor content against systemd/Podman unit syntax | **P0** | Prevents shipping broken units to servers — highest-value item in this tab. Could start simple (basic key/section validation) and grow. |
| 17 | *(needs redefinition)* Option to enable/disable the panel on the right side of the Editor | **P2** | The Editor already has an Inspector-collapse toggle (`inspector-expand-btn` / `toggleInspectorExpand()` in `static/main.js`), which does roughly what this item describes. Not clear if this item meant something different (e.g. a distinct "overview" panel rather than the Inspector) — flagged for you to clarify or drop. |
| 19 | Import a docker-compose file (and docker run commands) into a Quadlet unit via the Editor | **P1** | Use **PodletJS** (github.com/karoltheguy/PodletJS) — your own JS port of `podlet`, already supports full compose parsing (multi-service, networks, volumes, healthchecks, `depends_on`) and docker-run parsing. Since it's a plain npm package and this repo already vendors browser JS the same way (`xterm`, `xterm-addon-fit` copied into `static/` via the `copy-assets` script), the cleanest path is to vendor PodletJS the same way and run the conversion entirely client-side in the Editor — paste/upload compose YAML or a docker-run command, generate the quadlet content, load it into Monaco. No server round-trip needed. |

## Cross-cutting / infrastructure

| # | Item | Priority | Notes |
|---|------|----------|-------|
| 14 | Move to PostgreSQL for enterprise-grade / production-readiness (potential government use) | **P2, needs discussion** | Open issue **#173** already proposes SQLite WAL mode + `busy_timeout` as a lighter-weight fix, explicitly against an RDBMS migration unless the app goes multi-worker. That's the right call for *raw performance*. But "government / enterprise-grade" changes the calculus beyond performance — see chat discussion for the full reasoning on WAL's actual failure mode and when Postgres becomes worth it regardless of load. |
| 20 | Fix the row just beneath the Terminal/Logs button — its styling makes it look broken/empty | **P0** | Cheap visual bug, easy win, ship anytime. |
| 21 | Logo (top-left header + login page) | **P1** | No dependencies, but needs an actual asset — figure out branding source before implementation. |
