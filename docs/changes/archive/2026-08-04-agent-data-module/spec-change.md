# Spec Change: Agent Data Module

## Affected Spec Areas

- `docs/master/product/features/foundation-platform.md` — add Agent Data module description
- `docs/master/technology/modules/` — add Agent Data tech spec
- `docs/master/qa/` — add Agent Data test plan

## New Capabilities

- **Agent Data page** — A new page at `/admin/agent-data` that lists all intermediate data saved by agents via the `save_data` system tool, with filter/table/detail-drawer UX matching the Agent Outputs pattern
- **`agent::data` resource type** — New permission resource type for access control on agent intermediate data

## Modified Capabilities

- **Agent Trails page** — Before: three tabs (Executions, Results, Logs). After: two tabs (Executions, Logs). The "Results" tab is removed because it displays deprecated `ResultRecord` data that has been superseded by Agent Outputs.
- **Sidebar navigation** — Before: no "Agent Data" entry. After: new "Agent Data" entry under the Agents group, positioned after Data Types and before Agent Outputs.

## Removed Capabilities

- **Results tab / ResultRepositoryPage** — The `ResultRepositoryPage` component and its route `/results` are removed from the navigation and routing. The `ResultRecord` model and `ResultStore` service remain in the codebase (no DB changes).
- **`/results` route** — Removed from `AppRouter.tsx` (or redirected to `/admin/agent-data`).

## Spec Update Instructions

- Add "Agent Data" module description to `docs/master/product/features/foundation-platform.md`
- Update Agent Trails description to remove Results tab reference
- Add `agent::data` to the resource type manifest documentation
- Create `docs/master/technology/modules/agent-data/tech-spec.md` with Code Reference Map
- Create `docs/master/qa/test-plans/agent-data-test-plan.md`
