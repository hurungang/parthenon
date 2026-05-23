# Demo Cases: service-segregation-security-audit

## Grep Patterns
- Real Backend Integration - Service Segregation Deny Paths > internal authorize endpoint is wired and rejects missing service certificate
- Real Backend Integration - Service Segregation Deny Paths > internal system-tools endpoint is wired and rejects missing service certificate
- Real Backend Integration - Service Segregation Deny Paths > revocation contract endpoint uses revoked/{serial_number} path
- Browser Boundary - Frontend Uses API/WS Boundaries Only > dashboard traffic does not attempt direct database connections

## Scenario Details
| # | Feature | What it Shows | Spec File | Test Name |
|---|---|---|---|---|
| 1 | Internal authorize hardening | Internal authorization route is reachable and correctly denies unauthenticated internal access when a valid service certificate is missing (no 404/500 miswire). | e2e/tests/service-segregation-security-audit.spec.ts | Real Backend Integration - Service Segregation Deny Paths > internal authorize endpoint is wired and rejects missing service certificate |
| 2 | System tools boundary protection | Internal system-tools endpoint enforces service-certificate authentication and blocks direct unauthenticated invocation. | e2e/tests/service-segregation-security-audit.spec.ts | Real Backend Integration - Service Segregation Deny Paths > internal system-tools endpoint is wired and rejects missing service certificate |
| 3 | Revocation API contract correctness | Control Center revocation check uses the supported revoked/{serial_number} contract path and is operationally wired. | e2e/tests/service-segregation-security-audit.spec.ts | Real Backend Integration - Service Segregation Deny Paths > revocation contract endpoint uses revoked/{serial_number} path |
| 4 | Frontend service boundary behavior | Dashboard user journey sends traffic through API boundary only and does not attempt any direct database channel (postgres/supabase/5432). | e2e/tests/service-segregation-security-audit.spec.ts | Browser Boundary - Frontend Uses API/WS Boundaries Only > dashboard traffic does not attempt direct database connections |
