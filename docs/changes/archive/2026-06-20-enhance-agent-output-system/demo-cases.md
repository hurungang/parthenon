# Demo Cases: Enhance Agent Output System

<!-- Use with: /demo-app --cases docs/changes/enhance-agent-output-system/demo-cases.md -->

## Grep Patterns
<!-- Playwright --grep filter: one pattern per line, joined with | at runtime -->
- Agent Management > displays list of agent types from API
- Agent Management > shows create agent type button and opens dialog on click
- Result Repository > result repository shows result payload text

## Manual Demo Scenarios

These scenarios should be demonstrated manually since no e2e tests exist yet for the new pages:

### SC-1: Create and manage a Data Type
1. Navigate to Admin → Data Types (`/admin/data-types`)
2. Click "Create Data Type" — verify dialog opens with field editor
3. Create "IncidentReport" with fields: severity (enum: critical,high,medium,low), description (string, required), resolved (boolean), occurred_at (date)
4. Verify new type appears in the table with correct field count
5. Click edit — add a "priority" (number) field — verify update
6. Verify delete guard: create an agent type first that references IncidentReport, then try to delete — verify 409 with reference info

### SC-2: Assign Data Type to Agent Type and execute
1. Navigate to Agents → Agent Types (`/agents/types`)
2. Create/edit a non-conversational agent type
3. In "Output Configuration" section, select "IncidentReport" as the Output Data Type
4. Verify output_type changes to "typed" automatically
5. Save and verify the Agent Types table shows "IncidentReport" badge
6. Execute the agent — verify Result tab shows structured field view with "Result [IncidentReport]" badge

### SC-3: Agent Outputs Query Page
1. Navigate to Admin → Agent Outputs (`/admin/agent-outputs`)
2. Verify filter bar with data type, date range, agent type selectors
3. Select "IncidentReport" — verify table columns dynamically update to show field columns
4. Click a row — verify detail drawer opens with full field rendering
5. Click "Export CSV" — verify CSV file downloads with current filters

### SC-4: Validation Error Display
1. Execute an agent with invalid output (e.g., severity "unknown" when enum is critical/high/medium/low)
2. Verify execution completes (doesn't crash)
3. Open Result tab — verify prominent validation error banner
4. Verify raw output shown below as fallback
