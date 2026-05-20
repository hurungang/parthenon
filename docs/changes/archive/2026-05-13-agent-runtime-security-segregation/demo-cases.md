# Demo Cases: agent-runtime-security-segregation
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/agent-runtime-security-segregation/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match the test's describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Mocked — Certificate Authentication: Issue response excludes identity tokens > certificate issue response has cert/key but never identity tokens
- Mocked — Metadata Security: zero identity tokens at Agent Runtime boundary > authorization response: identity_token present at Communication Hub boundary (not Agent Runtime)
- Mocked — Tool Authorization Decision Outcomes > authorized=false: insufficient permissions — no token, includes reason
- Mocked — Certificate Revocation Response and Downstream Effects > after revocation: tool authorization returns unauthorized with revoked reason

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---------|---------------|-----------|-----------|
| 1 | Certificate Lifecycle | Admin issues a certificate and receives `certificate_pem`, `private_key_pem`, `serial_number`, and `expires_at` — confirming the cert carries no identity tokens (AC-1 one-time delivery to admin only) | e2e/tests/agent-security-segregation.spec.ts | certificate issue response has cert/key but never identity tokens |
| 2 | Security Boundary (Agent Runtime vs Communication Hub) | The `authorize/tool-call` response carries `identity_token` to the Communication Hub, but the certificate validate endpoint (Agent Runtime boundary) never does — demonstrating the token never crosses into Agent Runtime | e2e/tests/agent-security-segregation.spec.ts | authorization response: identity_token present at Communication Hub boundary (not Agent Runtime) |
| 3 | Authorization Flow — Permission Denial | An agent with a valid certificate but insufficient permissions receives `authorized=false`, a null identity token (no credential exposure on deny — AC-6 fail-safe), and a structured `reason` + `required_permission` for auditing | e2e/tests/agent-security-segregation.spec.ts | authorized=false: insufficient permissions — no token, includes reason |
| 4 | Certificate Revocation — Downstream Effect | After a certificate is revoked, a tool-call authorization using that serial number returns `authorized=false` with `reason: certificate_revoked` and a null identity token — proving revocation propagates immediately to tool access | e2e/tests/agent-security-segregation.spec.ts | after revocation: tool authorization returns unauthorized with revoked reason |

## Notes
- **Token refresh automation** is covered by backend integration tests only (`tests/integration/test_token_refresh_security.py`). No E2E scenario exists for that feature because E2E tests cannot drive token expiration timing reliably; the backend tests use mocked OAuth responses with deterministic clock behaviour.
- All four selected tests are mocked-API tests. The real backend integration counterparts (e.g. `Real Backend Integration — Tool Authorization Endpoint`) verify endpoint wiring but check only status codes, not business-logic behaviour — they are less informative for a product demo.
