# Operator dashboard

The daily interface is `www/f2.html`. It is a React + TypeScript dashboard using checked-in shadcn/ui components, with a single compiled HTML file for Home Assistant `/local`, add-on ingress, and GitHub Pages. The browser needs no CDN to load the primary dashboard.

## Find the right page

| Page | Job |
| --- | --- |
| Overview | Check room connection, alerts, moisture trends and zone readings. |
| Zones | Find a zone, inspect its readings and review changes to its enable switch. |
| Irrigation strategy | Edit discovered setpoints by zone and daily phase; review before applying. |
| Activity | Search and filter recorded controller messages; export the displayed events. |
| Sensors | Check sensor availability and reporting; find an entity by name. |
| Settings | Connect Home Assistant, change appearance and review the engine enable flag. |
| Help & tools | Read the phase glossary and open specialist planning/facility/diagnostic tools. |

`?room=room%3A` selects the empty-prefix default room; `?room=room%3Af1_` selects the named `f1_` room. Canonical identities preserve room scope even when default and named F2 coexist. Legacy `?room=f1`/`?room=f2` links are accepted; named prefixes take precedence, so use canonical links when you need an unambiguous default. An explicitly requested missing room stays unselected until you choose an available room. `?demo` explicitly enables isolated in-memory sample data. GitHub Pages also uses demo mode. Connection errors never switch live data to a demo. Hash routes such as `#zones`, `#strategy`, `#activity` and `#settings` support browser history.

The original console is preserved at `f2-classic.html`. It supports only the default and F1 prefixes; specialist links are disabled for other named rooms to avoid opening another room's controls. Classic return links use canonical room IDs. Other specialist pages have a shared return link. They retain their older dependencies and behavior; they are not redesigned primary pages. Older Alpine-specific screenshot scripts now target the classic console. New workflow verification is `frontend/scripts/verify-dashboard.mjs`.

## Connect and use

When embedded in Home Assistant, the adapter uses an available authenticated same-origin HA session. Otherwise use Settings to enter the Home Assistant URL and a token. New credentials are retained for the current tab session only; no credentials are bundled into the HTML. Direct cross-origin access requires HA to permit that origin. If it cannot connect, open the dashboard through the same HA origin or ingress.

Values that are missing, unknown or unavailable display as unavailable. VWC/EC readings require a valid `last_updated` timestamp and expire after 20 minutes by default (an explicitly exposed heartbeat/descriptor `max_sensor_age_s` can override this). Stale probes also appear unavailable in Sensors; static configuration values are not expired by this rule. An enabled flag means automation is allowed; it does not prove the controller is online or that hardware is watering. Current telemetry and recorded messages are separate from physical actuation evidence.

Parameter changes remain drafts while readings refresh. The review shows the room and before/after values. Apply calls only supported discovered configuration entities and checks their state afterward. Partial failures remain visible and the failed drafts are retained. A completed configuration write is not a claim about physical watering.

The new UI does not send legacy manual-shot/phase events or cross-room recipe services. The source audit found no consumer for those events in the shipped controller. Specialized legacy tools may assume an external controller; treat their event acknowledgement accordingly. Existing installations must not infer that changing a zone/system/auto flag interrupts an already running shot; use the documented controller kill flag for disarming.

## Develop and package

From the repository root (Node.js 24):

```sh
npm ci --prefix frontend
npm run dev --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
node frontend/scripts/verify-dashboard.mjs
node frontend/scripts/verify-live.mjs
```

For browser verification, install Chromium once with `cd frontend && npx playwright install chromium`, or set `PLAYWRIGHT_CHANNEL=chrome` to use installed Chrome. Browser verification starts its own loopback server and uses simulated HA API responses, never live Home Assistant.

The build writes `www/f2.html` and synchronizes known companion pages into `addons/f2_control/www/public/`. It does not publish, restart, rebuild, connect to HA, or copy user-owned experimental `aigrow-ops.html`. The original specialist source is `www/f2-classic.html`; never hand-edit the compiled `www/f2.html`.

Keep generated assets in the repository: GitHub Pages and a direct add-on Docker build must work from a clean checkout without Node at runtime. `npm ci` plus the lockfile reproduces the build. Frontend CI runs type checking/build, adapter tests and browser workflows; Python tests check the packaged dashboard contract.

## Source map

- `frontend/src/App.tsx`: application shell and navigation/draft state.
- `frontend/src/pages/`: task-specific pages.
- `frontend/src/components/`: shared charts, review/detail panels, shadcn primitives.
- `frontend/src/lib/types.ts`: UI/adapter interface.
- `frontend/src/lib/model.ts`: room and entity normalization.
- `frontend/src/lib/client.ts`: authenticated and validated HA calls.
- `frontend/src/lib/use-controller.ts`: lifecycle, polling and room state.
- `frontend/src/lib/demo.ts`: isolated demo fixtures.
- `frontend/scripts/package.mjs`: standalone artifact packaging.
- `www/dashboard-nav.js`: specialist-tool return navigation.

The shadcn component setup follows the [official Vite installation](https://ui.shadcn.com/docs/installation/vite). Source findings and verification evidence are in `docs/audits/2026-09-07-system-audit.md` and the accompanying UI/adapter reports.

Final integrated results: [verification report](audits/2026-09-07-final-verification.md).
