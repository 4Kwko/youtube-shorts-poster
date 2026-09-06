# SignalCut: frontend redesign

## Audit before editing
The frontend uses React 18, TypeScript, Vite and a Tauri desktop shell. Navigation
is driven by App state and resolveView, with Home, Projects, Settings, Processing
and Results views. Global CSS tokens and component classes define the styles;
Home and queue rules were duplicated across home.css and settings.css.
Lucide is available; there is no animation library or bundled web font.

Home collects URLs and local files in a client-side queue (maximum 20). queue.ts
parses whitespace/newlines/tabs, deduplicates and preserves insertion order.
App.start snapshots settings, calls the existing videos/batch and videos/local
endpoints, opens a single result directly or opens Projects for a batch.
Polling, export-folder behavior and snapshots must remain unchanged.

Visible Clipper branding was in Sidebar, the HTML title, Tauri product/window
labels and YouTube help copy. Internal package names, storage keys, Rust commands,
backend identifiers and previously selected folders stay compatible.

## Design
SignalCut uses charcoal/green-neutral surfaces and sparse lime accents. A split
S symbol represents a diagonal edit. Logo, wordmark and preview art are SVG.
Segoe UI uses the installed Windows font; system fallbacks need no network.
Shared buttons, badges, progress and timeline empty states avoid page-specific
variants. CSS transitions respect reduced motion. Compact navigation adapts to
tablet and mobile. Real pipeline stages and API statuses remain the source of truth.

## Scope
No changes to backend logic, database, API contracts, workers, jobs or Rust source.
Only display metadata and icon resources change in the desktop shell.

## Verification
- Run `npm run lint`, `npm test`, `npm run build` in frontend and `python -m pytest` at root.
- Start Vite, then run `node scripts/visual-qa.cjs` in frontend with Playwright available
  on NODE_PATH. Uses an isolated Edge context and intercepts all API calls with fixtures;
  it never creates real projects or uploads videos. Optional SIGNALCUT_QA_URL and
  SIGNALCUT_QA_BROWSER override the URL and browser channel.
- Covers URL/Enter, whitespace and multi-link input, invalid text, deduplication,
  removing/clearing, the 20-item limit, single/batch navigation, exact batch endpoint and
  settings snapshot, search, filters, empty/error states, modal Escape, reduced motion,
  and widths 1440/1280/1024/768/390. Captures live in ignored storage/design-qa.
- Component tests cover local selection, cancellation, mixed queues and disabled/loading.
- Native icons are generated from the SVG using the existing Tauri icon CLI. SVG remains
  the source of truth; PNG/ICO/ICNS are required native packaging exports.

## Compatibility and existing technical debt
- Validation on 2026-09-06: ESLint passed with zero warnings; 121 frontend tests and
  584 backend tests passed; TypeScript/Vite and the native Windows release build passed.
  Browser regression checks passed at all five viewport widths. No live upload was performed.
- Backend tests report dependency/HTTP-status deprecations in unchanged code. Native
  linking reports the MSVC library-creation message as a warning; the release succeeds.
- Project listing still loads the latest 30 records; stats explicitly describe that page.
  No fabricated global counts or additional statistics endpoints were introduced.
- Mixed URL/local submissions remain two separate API requests. Partial success can
  require manual reconciliation; changing this belongs to a later pipeline/API phase.
- The desktop executable still uses this checkout, Python environment and FFmpeg.
  A self-contained installer is outside this frontend-only phase.
- Internal package IDs, localStorage keys and existing chosen output paths keep their
  old identifiers so saved settings remain valid. New default folders use SignalCut.
