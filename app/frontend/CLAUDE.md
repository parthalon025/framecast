<!-- superhot-ui:0.4.0 -->
## superhot-ui Design System

**FrameCast surfaces: upload dropzone, photo grid, slideshow, stats page, offline banner, settings modals. Adjust failure theater to these surfaces — generic dashboard references below are for pattern reference only.**

This project consumes superhot-ui for all visual effects and UI components.
**Read these docs before implementing any UI in this project.**

### Reference Docs

- Integration: `node_modules/superhot-ui/docs/consumer-guide.md`
- Design philosophy: `node_modules/superhot-ui/docs/design-philosophy.md`
- Experience design: `node_modules/superhot-ui/docs/experience-design.md`
- Component docs: `node_modules/superhot-ui/docs/components/`

### Key Rules

**Typography — terminal voice, not web UI**
- Labels: UPPERCASE, `--tracking-widest`, `--text-muted`
- Values: numeric or terse — never prose
- Status text: lowercase monospace codes (`healthy`, `error`, `warning`)
- System messages: UPPERCASE authoritative (`SYSTEM DEGRADED` not "Some services are down")
- Empty states: never apologetic (`NO ACTIVE JOBS` not "No jobs found")

**Navigation — places, not functions**
- `TOPOLOGY` not "Graph", `SYSTEMS` not "Services", `QUEUE` not "Job Queue"
- Active route: phosphor left border — never filled highlight or background
- No hover tooltips — if a label needs one, it's too long

**Interface health states — whole interface changes at once**
- Operational: phosphor calm, no pulse, CRT scanlines only
- Degraded: ShThreatPulse + ShGlitch on affected surfaces, Incident HUD surfaces
- Critical: ShMantra on layout root, header pulses, all failed nodes pulse
- Rule: health state changes the whole interface simultaneously — never card by card

**Failure theater — 6 coordinated surfaces**
1. Graph node — `ShThreatPulse persistent`, color shifts to `--sh-threat`
2. Stat card — `status="error"` + `ShThreatPulse`
3. Sidebar — indicator dot pulses threat red
4. Incident HUD — `ShThreatPulse` + `ShMantra text="SYSTEM DEGRADED"`
5. Toast — `ShToast type="error" duration={0}` (persistent)
6. Layout root (critical only) — `ShMantra` watermarks entire interface

**Time-freeze discipline — data age is visible**
- Every data surface that can go stale wraps in `<ShFrozen timestamp={...}>` — no exceptions
- Fresh: 0–5min (full color), Cooling: 5–30min (desaturated), Frozen: 30–60min (grey), Stale: 60+min (ghost + NO DATA mantra)
- Header "last updated": `applyFreshness(el, timestamp)`

**Emotional arc — every session follows this loop**
Tension → Pause → Plan → Execute → Catharsis

- Page load: `ShSkeleton` everywhere (Tension → Pause)
- Data stale: `ShFrozen` activates, mantra appears (Tension)
- Service failure: `ShThreatPulse` + `ShGlitch` + `ShMantra` broadcast (Tension)
- Command palette opens: glitch burst — "I'm taking action" (Plan)
- Recovery: `ShGlitch` burst then phosphor calm (Catharsis)
- Job complete: `playSfx('complete')` if audio enabled (Catharsis)

**Interaction feedback — no silent actions**

| Action | Response |
|--------|----------|
| Open command palette | `ShCommandPalette` opens with glitch burst |
| Dismiss alert | `shatterElement` on the element |
| Job submitted | `ShToast type="info"` + `playSfx('complete')` |
| Job failed | `ShToast type="error" duration={0}` + `playSfx('error')` |
| Navigate route | `@starting-style` entrance on incoming content |
| Data refreshed | `ShGlitch` micro-burst on "last updated" timestamp |
| Service recovers | `ShGlitch` burst on node, then phosphor calm |

**Component rules**
- Every effect communicates exactly one signal — not "status plus action"
- Effects use only four palette colors: white (`--sh-bright`), black (`--sh-void`), red (`--sh-threat`), cyan (`--sh-phosphor`)
- New UI patterns go in superhot-ui first — never build a DS component directly in this project
- Components are diegetic — no decorative animation (no bounce, wiggle, idle flip)
- Layout components (grids, sidebars, nav) live in the consuming project, not superhot-ui

### Gotchas

- Never use `h` or `Fragment` as callback param names in JSX — esbuild injects `h` as JSX factory, shadowing it causes silent render crashes
- `shatterElement` requires `position: relative` on the parent element
- `--sh-fill` in `.sh-vram-bar` is a unitless number 0–100, not a percentage string (`72` not `"72%"`)
- `ShAudio.enabled` defaults to `false` — always set from user preference, never automatically
- `@import 'superhot-ui/css'` fails silently inside inline `<style>` blocks (no base URL) — inject as separate `<style>` elements
- esbuild + `file:` dep: pin all Preact imports in `esbuild.config.mjs` to avoid dual-Preact crash (see consumer-guide.md)
