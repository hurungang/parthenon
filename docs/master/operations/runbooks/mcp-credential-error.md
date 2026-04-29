# Runbook: MCP Session Credential Errors

## Symptoms

- MCP tool calls fail with authentication errors directed at the external MCP server
- Logs from `mcp-hub` contain `credential decryption failed` or `session not found`
- Agents that invoke tools backed by the affected MCP server receive error responses or timeouts
- The issue is typically scoped to one MCP server or one named session rather than all servers

---

## Resolution Steps

1. Verify that the `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` environment variable is set correctly on the MCP Hub service and has not changed since the affected session's credentials were originally stored. Decryption will fail silently if the key has been rotated — the credentials cannot be recovered without the original key. If the key has changed, the affected sessions must have their credentials re-entered.

2. Confirm that the named session referenced in the failing tool calls exists in the platform. Check the MCP Hub admin page for the affected server and verify the session is listed and its identity or role mapping is correct. A missing session record means the session was deleted after the agent's configuration was set up.

3. Check the external MCP server's own authentication and access logs to determine whether the failure is caused by a bad or expired credential versus a network or TLS issue. If the MCP server logs show no inbound connection attempts, the failure is occurring before the proxy makes the outbound call — indicating a decryption or session lookup problem on the Parthenon side.

4. If the credential is confirmed to be invalid or expired, re-enter the credentials for the affected session via the MCP Hub admin UI. The MCP Hub will encrypt the new credentials using the current `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` and store them, replacing the previous values.

---

## Notes

- Credential values are never logged in plaintext — logs will only contain error indicators, not the credential itself
- If multiple sessions across different MCP servers are failing simultaneously, the most likely cause is a key rotation event rather than individual credential expiry — check `MCP_HUB_CREDENTIAL_ENCRYPTION_KEY` first
- After re-entering credentials, trigger a test tool call from the MCP Hub admin UI to confirm the new credentials are working before assuming the issue is resolved
