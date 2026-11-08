# Agent Client Demo App

A tiny standalone web app that lets you **talk to a Parthenon agent type** (or
submit a request and get a typed response) using just a **client secret**.

A *client* is a third-party integration access grant bound to one agent type. It
is **not** an agent identity — it only invokes the agent type's input interface
(conversation or request/response). It never grants tool or identity access.

---

## Prerequisites

1. **Python 3.11+** (the demo uses the repo project venv `../.venv` automatically; or set
   `PYTHON=/path/to/python3.11`). The macOS system `python3` is 3.9 and will NOT work.

2. **Parthenon backend running** (Control Center + Communication Hub + Agent Runtime).
   On macOS: `./scripts/restart-backend.sh`. On Windows: `.\parthenon.ps1 restart -Services backend`.

2. **Integration gateway enabled** on the Communication Hub. Set these env vars for
   the CH service (then restart it):
   ```
   INTEGRATION_GATEWAY_ENABLED=true
   INTEGRATION_PUBLIC_BASE_URL=http://localhost:8002
   ```
   The CH listens on `http://localhost:8002` by default.

3. **An agent type + a client** for it:
   - Open the Parthenon web UI → **Agents** → click your agent type → **Clients** tab →
     **New Client**.
   - Choose **secret (server-side)**, set a name, optionally set allowed origins and a
     rate limit, and save.
   - Copy the **client secret** (`phn_cl_sk_…`) shown once. You will paste it into the
     demo app.

   > Prefer the API? `POST /api/v1/clients` with
   > `{"name":"demo","agent_type_id":"<id>","key_type":"secret"}` (JWT admin) returns the
   > clear-text `client_key` once.

---

## Run the demo

```bash
cd agent-client-demo-app

# macOS / Linux
./start.sh

# Windows (PowerShell)
.\start.ps1
```

Then open **http://localhost:7002**.

To stop:

```bash
./stop.sh        # macOS / Linux
.\stop.ps1       # Windows
```

(Override the port with `PORT=7003 ./start.sh`.)

---

## Use it

1. **Communication Hub base URL** — leave the default `http://localhost:8002`
   (or point at your CH).
2. **Client credential** — paste the `phn_cl_sk_…` (secret, **Server-side** tab) or
   `phn_cl_pk_…` (publishable, **Browser widget** tab) you copied when creating the client.
3. Click **Connect**.
   - The app shows the target agent type, its input mode, and the tenant.
   - **Conversational** agent type → **Start session**, then a chat box. Messages in the
     same session share context (stateful, like the Control Center chat); **End session**
     closes it.
   - **Typed** agent type → an input form **auto-generated from the agent type's declared
     input schema** (no chat surface). Enter the input and click **Submit**; the validated
     typed result appears. If the type declares no schema, a raw JSON input is shown.

The demo polls the execution session until it completes (the platform executes
agents asynchronously), then shows the reply/output.

---

## Two tabs

The demo has two integration modes:

1. **Server-side (secret)** — paste a `phn_cl_sk_…` secret. The demo backend proxies to
   the gateway. **Origin is irrelevant here** — the secret is the authentication.
2. **Browser widget (publishable)** — paste a `phn_cl_pk_…` publishable key. The **browser
   calls the gateway directly**; the browser sets `Origin` automatically (page JS cannot
   override it — it's a forbidden header), so the allowlist is enforced by the browser.

## Testing a publishable key

For the **Browser widget** tab, the client's **allowed origins** must include this page's
origin — **`http://localhost:7002`** (if you serve the demo on another port, add that
origin instead). There is no Origin field: the browser supplies it. A user-editable origin
would let anyone spoof an allowlisted site — the exact thing the allowlist prevents.

(For the Server-side tab, origin does not apply — the secret authenticates the call.)

## How it works

```
Server-side tab:
  Browser ──► demo backend (:7002) ──► CH /integrate/*  (Authorization: Bearer phn_cl_sk_…)

Browser-widget tab:
  Browser ──► CH /integrate/* directly  (Authorization: Bearer phn_cl_pk_…; Origin set by the browser)
```

The server-side tab never stores the secret; it forwards it as a bearer credential on each
request. The browser-widget tab sends the publishable key from the browser — which is safe
because the key is public and origin-restricted.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `Connection failed: 404` | Gateway not enabled | Set `INTEGRATION_GATEWAY_ENABLED=true` on CH and restart it |
| `Connection failed: 401` | Wrong/revoked secret, or client inactive | Re-copy the secret; check the client isn't deactivated |
| `Connection failed: 403 Origin not allowed` | The client's allowlist doesn't include this demo's origin (`http://localhost:7002`) | Add `http://localhost:7002` to the client's allowed origins |
| `Connection failed: 429` | Rate limit hit | Raise the client's rate limit |
| Session stays `queued`/`running` | Agent Runtime not running / agent error | Check `backend/logs/agent-runtime.log` |
| `404 Session not found` | Wrong CH base URL or session expired | Verify the base URL |

---

## Security notes

- Use a **secret** client here (server-side). Only ever put a **publishable**
  client in a browser.
- The client is **not an identity** — it cannot list/call tools, reach the MCP hub,
  or impersonate an agent.
- The demo app is for local development only.
