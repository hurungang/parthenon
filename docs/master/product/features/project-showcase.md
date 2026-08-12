# Project Showcase

## Overview
The Project Showcase is a public-facing static website published to GitHub Pages that communicates Parthenon's architecture, security model, and key capabilities to platform evaluators, prospective contributors, and executive stakeholders. It combines a high-level design overview with a guided walkthrough of five end-to-end workflows, enabling anyone to understand what Parthenon does, how it is architected, and how to use it — without requiring access to a running instance.

## Who Uses It

- **Platform Evaluators**: Engineers and architects assessing whether Parthenon fits their enterprise AI governance and agent management requirements. They need a clear overview of architecture, security controls, and key capabilities to make a build-vs-buy decision.
- **Prospective Contributors**: Developers and internal teams evaluating the codebase structure and contribution areas before engaging. They need enough context to understand how the platform is decomposed and where to start.
- **Executive Stakeholders**: Decision-makers who need a high-level, non-technical overview of what Parthenon does and why it matters. They benefit from the polished presentation and business-level descriptions.
- **Existing Operators**: Teams already deploying Parthenon who want a reference walkthrough for onboarding new team members or demonstrating the platform to peers.

## What It Does

- Provides a publicly accessible, navigable website presenting Parthenon's architecture, security model, and key workflows in business-readable language.
- Delivers a **High-Level Design** section explaining the platform's architecture: SOP/Skill-driven MCP integration, the tools permission control chain, the three-service backend decomposition, and the dual-identity model.
- Delivers a **Demo / Walkthrough** section with dedicated pages covering five end-to-end workflows: integrating an MCP server, creating Skills and SOPs, creating Agent Roles, creating Agent Types and triggering agents, and viewing execution logs.
- Uses clearly labeled placeholder images at every point where a live application screenshot would appear, allowing operators to substitute real screenshots at any time.
- Publishes automatically to GitHub Pages on every push to the main branch via CI/CD — no manual deployment steps required.
- Runs as purely static HTML, CSS, and JavaScript with no backend server or runtime dependencies.

## Key Concepts

### High-Level Design Section

The High-Level Design section communicates Parthenon's architecture at a business level, structured around four architectural pillars:

- **SOP/Skill-Driven MCP Integration**: Describes how Skills wrap individual MCP tool calls and SOPs compose them into governed, multi-step workflows. Explains how this architecture decouples tool integration from execution logic, enabling reusable, permission-controlled agent capabilities.

- **Tools Permission Control Chain**: Explains the full governance chain from MCP tool registration through Skills, Agent Roles, and Agent Identities. Illustrates how tool access is never granted directly — it flows through the Skill → Role → Identity chain, ensuring every tool invocation is authorized against a defined role and bound to a specific agent identity.

- **Three-Service Backend Decomposition**: Breaks down the responsibilities of the three backend services: **Control Center** (governance, policy management, and operational oversight), **Communication Hub** (message brokering, WebSocket connections, session context, and agent-to-agent routing), and **Agent Runtime** (agent instance lifecycle, execution, and tool invocation). Explains why these are separated for security isolation and independent scalability.

- **Dual-Identity Model**: Explains the human realm and agent realm topology. Covers why agent identities are first-class OIDC principals separate from human users, how the Communication Hub propagates both identities independently, and the security rationale for keeping them isolated — preventing agent actions from being misattributed to human operators and vice versa.

### Demo / Walkthrough Section

The Demo / Walkthrough section provides a guided, step-by-step experience through five key workflows, each on its own page:

1. **Integrating an MCP Server**: Walkthrough of registering an external MCP server, configuring sessions (including passthrough), syncing available tools, and verifying the tool catalog appears in the platform. Shows how tools become available for Skill packaging.

2. **Creating Skills and SOPs**: Walkthrough of defining a Skill that wraps one or more MCP tools with permission constraints, then composing multiple Skills into an SOP with sequential and conditional steps. Demonstrates how SOPs create repeatable, governed workflows from individual tool capabilities.

3. **Creating Agent Roles**: Walkthrough of defining an Agent Role, selecting which MCP servers and tools the role can access, and assigning that role to agent identities. Shows the permission chain in action — how tool access flows from MCP server registration through role assignment.

4. **Creating Agent Types and Triggering Agents**: Walkthrough of defining an Agent Type with execution guardrails (max instances, model selection, allowed SOPs), then triggering agent instances both in non-conversational (fire-and-forget) and conversational (interactive) modes. Demonstrates the dual-mode execution model.

5. **Viewing Execution Logs**: Walkthrough of navigating execution history, inspecting agent trails and conversation history, reviewing results and intermediate data saves, and understanding the audit trail. Shows how Parthenon provides full observability into every agent action.

### Placeholder Image Convention

Where live screenshots of the running Parthenon application are referenced, the showcase uses clearly labeled placeholder images. Placeholders are annotated with descriptive captions identifying what a real screenshot would show (e.g., "Screenshot: MCP Server registration form with fields populated"). This convention ensures reviewers and visitors are not misled into thinking placeholders are actual screenshots, while making it straightforward for operators to swap in real images when available.

### Automated Publication

The showcase site is published through a CI/CD workflow that triggers on every push to the main branch. The workflow builds the static site and deploys to GitHub Pages with no manual intervention. The site is purely static — no server-side runtime, no database, no backend — and is served directly from a content delivery network.

## Acceptance Criteria

### Site Availability
- The site is accessible at the project's GitHub Pages URL after merging to the main branch.
- The CI/CD workflow automatically builds and publishes the site on every push to main.
- The site loads correctly in modern browsers (Chrome, Firefox, Safari, Edge) without errors.

### High-Level Design Section
- The site includes a dedicated section clearly explaining SOP/Skill-driven MCP integration in business-readable language.
- The site clearly communicates the tools permission control chain — from MCP server through Skills, Roles, and Identities.
- The site explains the three-service backend decomposition and the responsibility of each service.
- The site explains the dual-identity model, including what each realm represents and why the separation matters.

### Demo / Walkthrough Section
- The site includes dedicated pages for all five workflows: MCP server integration, Skill and SOP creation, Agent Roles, Agent Types and triggering, and execution logs.
- Each walkthrough page describes steps in logical order, oriented toward what the user does and why.
- Placeholder images are clearly distinguishable from real screenshots and include descriptive captions.

### Presentation Quality
- The site uses a professional visual design appropriate for a project showcase.
- The site is fully navigable as static HTML/CSS/JS — no backend required.
- The site is responsive on both desktop and mobile screen sizes.
- No broken links or missing assets are present on any page.

### Build and Deployment
- The CI/CD workflow handles any build steps automatically.
- The build produces a static output served directly by GitHub Pages.
- The site requires no server-side runtime, database, or dynamic backend.

## Out of Scope

- Live demo environment or embedded live API access — the site is purely informational and static.
- User authentication, login, or any interactive features requiring a backend.
- Automated screenshot capture from a running Parthenon instance — screenshots are manual placeholders only.
- Technical contributor documentation (API references, developer guides) — those remain in the repository's existing docs.
- Multi-language or i18n support.
- Search functionality.

## Dependencies & Constraints

- The site must be compatible with GitHub Pages static hosting constraints (no server-side execution).
- The CI/CD workflow must use only standard provided runners with no external secrets required for the basic build and publish step.
- Architecture descriptions in the showcase must accurately reflect the platform's actual design as documented in master architecture docs — no contradictions permitted.
- Placeholder images must be clearly distinguishable from real screenshots so visitors are not misled.
- The showcase is the canonical public-facing description of the platform; any significant architecture changes must be reflected in the showcase content.
