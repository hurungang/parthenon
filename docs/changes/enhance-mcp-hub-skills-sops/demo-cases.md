# Demo Cases: enhance-mcp-hub-skills-sops

Demo cases showing key features. Each case maps to a Playwright E2E test.

## How to Run

```bash
cd e2e
npx playwright test --grep "<pattern>" --config playwright.dev.config.ts
```

Run all tests for this change:

```bash
cd e2e
npx playwright test tests/mcp-hub.spec.ts tests/skills-sops.spec.ts --config playwright.dev.config.ts
```

---

## Demo Cases

### 1. MCP Hub Server List
**What it shows:** MCP Hub renders the server list with names, status indicators, and a Register Server button
**E2E test:** `npx playwright test tests/mcp-hub.spec.ts --grep "MCP Hub shows server names"`
**Steps:**
1. Navigate to `/mcp`
2. Observe server list loads with "Internal Tools" and "External Research"
3. Observe active/inactive status indicators on each server
4. Verify "Register Server" button is present

---

### 2. Register / Add MCP Server
**What it shows:** Opening the Register Server dialog from the MCP Hub
**E2E test:** `npx playwright test tests/mcp-hub.spec.ts --grep "has a register/add server button"`
**Steps:**
1. Navigate to `/mcp`
2. Click the "Register Server" button
3. Verify a dialog opens for entering server details

---

### 3. MCP Session with Identity Binding
**What it shows:** MCP session data carries `identity_binding` (agent/realm) and `credential_config` (required keys), and never exposes `encrypted_credentials`
**E2E test:** `npx playwright test tests/mcp-hub.spec.ts --grep "MCP Session CRUD"`
**Steps:**
1. Navigate to `/mcp`
2. Observe server list loads without errors
3. Verify session API contract includes `identity_binding: { agent_id, realm }` and `credential_config: { required_keys }`
4. Verify `encrypted_credentials` is never present in the session response

---

### 4. Skills Page with Tool Binding Count and Status
**What it shows:** Skills list renders skill names, descriptions, tool binding counts, and active/inactive status
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "Skills > skills page lists skill names from API"`
**Steps:**
1. Navigate to `/skills`
2. Observe "Summarise Text", "Send Email", and "Web Search" listed
3. Verify descriptions are displayed ("Summarises long text", "Sends an email via SMTP")
4. Verify active/inactive status indicators are present

---

### 5. Skills API Includes `instructions` and `tool_ids` Fields
**What it shows:** The skills API schema exposes the new `instructions` field (agent-facing guidance) and `tool_ids` array (multi-tool binding)
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "Skill editor with instructions and tool binding > skills API response includes instructions field"`
**Steps:**
1. Navigate to `/skills`
2. Observe the API response for "Summarise Text" includes `instructions: "Call this tool with the user query."`
3. Verify `tool_ids` is an array (e.g., `["tool-1"]`)
4. Verify both fields are present even when `instructions` is `null`

---

### 6. Create Skill with Instructions
**What it shows:** The skill creation form accepts an `instructions` field; submitted payload includes it
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "Skill editor with instructions and tool binding > create skill POST payload can include instructions field"`
**Steps:**
1. Navigate to `/skills`
2. Click "Create Skill"
3. Fill in the instructions field with agent guidance text
4. Submit and verify the POST payload includes the `instructions` field

---

### 7. SOPs Page with Step Count
**What it shows:** SOPs list renders SOP names, descriptions, step counts, and active status
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "SOPs > SOPs page lists SOP names from API"`
**Steps:**
1. Navigate to `/sops`
2. Observe "Onboarding SOP" (3 steps) and "Incident Response" (5 steps) listed
3. Verify step count is displayed for each SOP
4. Verify descriptions are present ("New employee onboarding", "Handle incidents systematically")

---

### 8. SOP Step Detail View
**What it shows:** Clicking a SOP reveals its ordered steps (skill_invocation type with named steps)
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "SOPs > clicking a SOP shows its steps"`
**Steps:**
1. Navigate to `/sops`
2. Click "Onboarding SOP"
3. Verify steps are displayed: "Collect user info", "Send welcome email", "Schedule follow-up"

---

### 9. SOP Steps Use `skill_invocation` Step Type
**What it shows:** SOP steps use the correct `skill_invocation` enum value (not the legacy `skill` type) and expose new `target_agent_type_id` and `step_config` fields
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "SOP editor with instructions and steps > SOP steps use skill_invocation type (not legacy skill)"`
**Steps:**
1. Navigate to `/sops`
2. Open any SOP to view its steps
3. Verify all steps report `step_type: "skill_invocation"`
4. Verify step schema includes `target_agent_type_id` and `step_config` fields

---

### 10. SOPs API Includes `instructions` Field
**What it shows:** The SOPs API schema exposes the `instructions` field for workflow-level agent guidance
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "SOP editor with instructions and steps > SOPs API response includes instructions field"`
**Steps:**
1. Navigate to `/sops`
2. Observe API response for "Onboarding SOP" includes `instructions: "Follow these steps in order."`
3. Verify field is present even when `null` (as in "Incident Response")

---

### 11. Create SOP with Instructions
**What it shows:** The SOP creation form accepts an `instructions` field; submitted payload includes it
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "SOP editor with instructions and steps > create SOP POST payload can include instructions field"`
**Steps:**
1. Navigate to `/sops`
2. Click "Create SOP"
3. Fill in the instructions field with workflow guidance
4. Submit and verify the POST payload includes the `instructions` field

---

### 12. Auto-Generated Tool Reference Section in Skill Instructions
**What it shows:** When tools are bound to a skill, the backend automatically appends a `## Tools` section to `instructions_with_tools` — listing each tool's name, description, and JSON input schema. This field is read-only and never sent back in create/update requests.
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "Skill editor — Generated Tool Reference section > instructions_with_tools API contract includes Tool Section marker"`
**Steps:**
1. Navigate to `/skills`
2. Observe a skill that has tool bindings (e.g., "Search Skill" bound to `internal-tools/search`)
3. Verify the `instructions_with_tools` API field starts with the user-provided instructions text
4. Verify the field contains a `## Tools` section with the tool slug (`internal-tools/search`), its description, and an `Input Schema` JSON block
5. Verify `instructions_with_tools` is absent from the POST/PUT request body (computed by backend, not submitted by client)

---

### 13. Default Skills Created on Installation
**What it shows:** During application seeding, two default skills — `save_result` and `send_notification` — are automatically created so agents have standard output capabilities without manual setup.
**E2E test:** `npx playwright test tests/skills-sops.spec.ts --grep "Real Backend Integration — Default Skills > default skills save_result and send_notification are present after seeding"`
**Steps:**
1. Ensure the backend is running with seeding applied (`alembic upgrade head` + seed fixtures)
2. Call `GET /api/v1/skills` on the real backend (no mock)
3. Verify the response list contains a skill named `save_result`
4. Verify the response list contains a skill named `send_notification`

> **Note:** This test skips gracefully when the backend is not reachable (e.g. CI without a full service stack). It also accepts `401`/`403` as valid responses when authentication is required, since the default skills are then verified by backend pytest integration tests.
