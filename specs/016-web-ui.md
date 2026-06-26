# 016 — Web UI

## Summary

A minimal, server-rendered admin UI. Preserves the structure and feel of the Python/HTMX UI but is bundled into the Go binary via `//go:embed`. No separate frontend build, no Node toolchain, no SPA.

## Technology stack

- **Rendering**: `html/template` (stdlib).
- **Interactivity**: HTMX (served as a vendored static file).
- **Styling**: hand-written CSS, vendored. No Tailwind, no PostCSS, no build step.
- **Assets**: embedded via `//go:embed web/templates web/static`.

## Directory layout

```
web/
├── templates/
│   ├── layout.html           # shared shell (nav, flash, user menu)
│   ├── login.html
│   ├── pages/
│   │   ├── applications.html
│   │   ├── actions.html
│   │   ├── events.html
│   │   ├── subscriptions.html
│   │   ├── gists.html
│   │   └── redactions.html
│   └── windows/              # HTMX-loaded modal fragments
│       ├── application_form.html
│       ├── action_form.html
│       ├── subscription_form.html
│       ├── redaction_form.html
│       └── event_detail.html
└── static/
    ├── css/amebo.css
    ├── js/
    │   ├── htmx.min.js       # vendored
    │   └── amebo.js          # small glue (e.g., copy-to-clipboard)
    └── img/logo.svg
```

## Routes

| Method | Path | Handler | Purpose |
|---|---|---|---|
| GET | `/` | login | Show login form (or redirect to `/p/applications` if authed) |
| POST | `/login` | loginSubmit | Form post; sets cookie; redirects to `/p/applications` |
| GET | `/p/:page` | page | Render a full page with layout |
| GET | `/w/:name` | window | Render a modal/fragment (HTMX target) |
| POST | `/logout` | logout | Clear cookie; redirect to `/` |
| GET | `/public/*` | static | Serve embedded static assets |

Pages: `applications`, `actions`, `events`, `subscriptions`, `gists`, `redactions`, `cluster`.

## Auth

All `/p/*` and `/w/*` routes require the admin cookie (spec 009). On missing/expired cookie, redirect to `/?next=<path>`. After login, bounce to `next` or `/p/applications`.

The UI does not hold API keys or secrets; it acts on behalf of the logged-in admin against the same `/v1/*` endpoints.

## HTMX patterns

- **Page scaffolding**: full page render with layout + page content.
- **Dynamic lists**: `<div hx-get="/w/applications/list?page=1" hx-trigger="load">` — the fragment re-renders the table.
- **Forms**: `<form hx-post="/v1/applications" hx-target="#modal">` — response is a fragment replacing the modal.
- **Pagination**: HTMX-swapped pagers update the list in-place.
- **Flash messages**: `HX-Trigger` response header signals the client to show a toast.

## Pages

### Applications (`/p/applications`)

Table: name, address, active, created_at, actions (toggle, rotate api_key, delete). "New application" button opens `/w/application_form`. Response from POST shows the one-time `api_key` and `secret` in a modal with copy buttons.

### Actions (`/p/actions`)

Table: action, application, created_at, actions (view schema, delete). "New action" opens a form with an embedded JSON editor (plain textarea — no CodeMirror dependency in v1).

### Events (`/p/events`)

Table: id, action, deduper, created_at, fan-out count, actions (view, replay). Filters: action, application, time range. Payloads displayed are **redacted** (spec 014). Raw payload is not exposed to the UI.

### Subscriptions (`/p/subscriptions`)

Table: id, subscriber app, action, handler URL, max_retries. Actions: edit, delete, replay-all-pending-gists-for-this-sub.

### Gists (`/p/gists`)

Table: id, event, subscription, retries, completed, sleep_until, last_error (truncated). Filters: event, subscription, completed. Actions: replay, acknowledge.

### Redactions (`/p/redactions`)

Table: action, field_path. Add via form; delete inline. Immediate cache invalidation flash.

### Cluster (`/p/cluster`)

Read-only topology view: leader, nodes, states, last contact, applied index. Admin actions: trigger snapshot, transfer leadership (with confirmation prompt).

## Fragment rendering

```go
// internal/ui/window.go
func Window(name string) http.HandlerFunc {
    tmpl := templates["windows/"+name+".html"]
    return func(w http.ResponseWriter, r *http.Request) {
        data, err := collectData(r, name)
        if err != nil { httpErr(w, err); return }
        tmpl.ExecuteTemplate(w, "content", data)
    }
}
```

## Static asset serving

Content-hashed filenames for cache-busting:

```go
//go:embed web/static
var staticFS embed.FS

func StaticHandler() http.Handler {
    sub, _ := fs.Sub(staticFS, "web/static")
    return http.FileServer(http.FS(sub))
}
```

Emitted URLs: `/public/css/amebo.<hash>.css`. The build injects the hash into templates via a template function `{{ asset "css/amebo.css" }}`.

## Security

- CSRF: all form POSTs include a CSRF token (stored in cookie, mirrored in a hidden form field). Verified middleware on `POST /p/*` and `/logout`. `/v1/*` is exempt because it uses signatures/cookies, not forms.
- CSP: `default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self';`. Inline styles allowed for HTMX hx-indicator markup.
- No external CDN resources. Everything vendored.

## Accessibility

- Semantic HTML (table, thead, nav, main).
- Keyboard nav: all interactive elements focusable.
- Contrast WCAG AA for default CSS.
- Form labels associated with inputs.
- Target: Lighthouse accessibility score ≥ 90.

## Internationalization

Not in v1. English only. Strings centralized in `web/templates/_strings.html` for future extraction.

## Dark mode

CSS uses `prefers-color-scheme`. Two themes from the start. No toggle in v1 (follows OS).

## Observability

- Access log entries distinguish UI vs API by `path` prefix — no separate metric.
- UI-specific metric: `amebo_ui_login_total{result="ok|fail"}`.

## Acceptance criteria

- [ ] `go build` produces a binary that serves the full UI with no external files.
- [ ] Logging in, creating an application, registering an action, publishing an event (via a CLI call), and seeing the event appear in the UI works end-to-end.
- [ ] CSP headers present; browser console has no violations.
- [ ] CSRF token required for POSTs; missing token yields 403.
- [ ] Lighthouse accessibility ≥ 90.
- [ ] Page loads in < 200 ms on localhost.

## Alternatives considered

- **React / Vue SPA**: bigger, needs Node build, clashes with "single binary" story. Rejected.
- **Templ (a-h/templ)**: typed templates, very nice DX. Considered seriously; rejected for v1 to minimize tooling (adds a generator step). Revisit for v1.1.
- **Preact + island hydration**: no build step is the goal; Preact still needs bundling.
- **Keep only an API with a separate UI repo**: drops a useful onboarding surface. Rejected.
