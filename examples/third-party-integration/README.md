# Third-Party Agent Integration — Runnable Example

> For a full **UI demo** (paste a client secret, then chat or submit and see the
> response), use the standalone demo app in [`agent-client-demo-app/`](../../agent-client-demo-app/README.md)
> (`./start.sh` → http://localhost:7002). This folder is a minimal scripted example.

This example exercises the Parthenon third-party agent-integration flow end to
end against a local Parthenon instance using the Python SDK.

## Prerequisites

1. Parthenon backend running locally (`./scripts/restart-backend.sh` on macOS, or
   `.\parthenon.ps1 restart -Services backend` on Windows).
2. The integration gateway enabled on the Communication Hub:
   ```
   INTEGRATION_GATEWAY_ENABLED=true
   INTEGRATION_PUBLIC_BASE_URL=http://localhost:8002
   ```
3. An agent type created in the tenant (conversational or typed).
4. A **client** created for that agent type (via the management UI or
   `POST /api/v1/clients`), yielding a `phn_cl_sk_…` (secret) or
   `phn_cl_pk_…` (publishable) credential.

## Run

```bash
export PARTHENON_BASE_URL=http://localhost:8002
export PARTHENON_CLIENT_KEY=phn_cl_sk_...
python example.py
```

The script prints the client's white-label config, then submits input to the
agent type and prints the execution session id (the platform executes agents
asynchronously — poll the session for the final typed result).

## Security notes

- The client credential grants access to **one agent type's input interface
  only** — never to tools, the MCP hub, or an agent identity.
- Use a `secret` credential server-side; only ever put a `publishable`
  credential in a browser.
