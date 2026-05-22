# Spec Change: GitHub Pages Project Showcase

## Affected Spec Areas

- `docs/master/product/` — New capability: public showcase site as a platform deliverable
- `docs/master/architecture/` — The showcase's architecture section must accurately reflect the three-service decomposition (Control Center, Communication Hub, Agent Runtime) and dual-realm identity model; this change does not alter the backend architecture but does produce a public-facing representation of it
- `docs/master/deployment/` — New deployment target: GitHub Pages via GitHub Actions CI/CD workflow

---

## New Capabilities

### Public Project Showcase Website
A new static website is introduced as a first-class platform deliverable, published to GitHub Pages. This capability did not exist previously.

**What it provides:**
- A publicly accessible, navigable site presenting Parthenon's architecture, security model, and key workflows
- A **High-Level Design section** covering:
  - SOP/Skill-driven MCP integration architecture — how skills and SOPs compose MCP tool calls into governed, permission-controlled agent capabilities
  - Tools permission control system — how tool access is granted through the skill → role → agent identity chain
  - Three-service backend isolation — the responsibilities of Control Center, Communication Hub, and Agent Runtime and why they are separated
  - Dual-identity model — the human realm and agent realm topology and the security rationale for keeping them separate
- A **Demo / Walkthrough section** with dedicated pages covering five end-to-end workflows:
  1. Integrating an MCP server into the platform
  2. Creating Skills and SOPs
  3. Creating Agent Roles
  4. Creating Agent Types and triggering agents (non-conversational and conversational modes)
  5. Viewing execution logs
- Clearly labeled placeholder images at every point where a live screenshot of the running application would appear, allowing operators to substitute real screenshots at any time

### Automated Publication via GitHub Actions
A new GitHub Actions workflow is introduced that automatically builds and publishes the showcase site to GitHub Pages on every push to the main branch. This is a new CI/CD pipeline path with no equivalent in the existing pipeline.

---

## Modified Capabilities

None. This change adds a net-new deliverable and does not modify any existing platform features, backend services, frontend application, or database schema.

---

## Removed Capabilities

None.

---

## Spec Update Instructions

The following updates are required to master product spec files once this change is implemented:

- **`docs/master/product/`**: Add a new spec file (e.g., `project-showcase.md`) describing the GitHub Pages showcase as a platform deliverable — its purpose, structure (High-Level Design section + Demo/Walkthrough section), and the placeholder image convention.
- **`docs/master/deployment/`**: Add a section documenting the GitHub Pages deployment target — the GitHub Actions workflow, the branch trigger (main), and the build output directory. Note any configuration required for custom domain support.
- **`docs/master/architecture/`**: No structural changes required. However, verify that the architecture diagrams used in the showcase accurately reflect the current master architecture docs; flag any discrepancies for the architect agent to resolve before the showcase is published.
- **`docs/master/reference/`** (optional): Consider adding a brief entry in the reference docs explaining that the GitHub Pages showcase is the canonical public-facing description of the platform and linking to it.
