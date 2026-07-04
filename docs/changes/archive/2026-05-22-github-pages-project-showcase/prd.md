# PRD: GitHub Pages Project Showcase

## Epic Overview

The Parthenon platform currently has no public-facing presence to communicate its capabilities, architecture, and value proposition to prospective adopters, evaluators, and contributors. This change introduces a polished static website published to GitHub Pages that serves as a professional project showcase — combining a high-level design overview of the platform's architecture with a guided walkthrough of its key workflows. The site enables anyone to understand what Parthenon does, how it is architected, and how to use it, without requiring access to a running instance.

---

## Business Goals

- Reduce time-to-understanding for new evaluators from hours to minutes by providing a self-service showcase with architecture diagrams and guided demos.
- Establish Parthenon's professional credibility as an enterprise-grade AI harness platform through a polished, well-structured public website.
- Increase adoption and contributor interest by making the platform's capabilities discoverable and understandable without prior context.
- Provide a reusable, maintainable showcase that can be updated as the platform evolves, with clear placeholder conventions for screenshots.
- Enable the showcase to be automatically published on every main-branch update via GitHub Actions, requiring zero manual deployment effort.

---

## Users & Personas

**Platform Evaluators** — Engineers or architects assessing whether Parthenon meets their enterprise AI governance and agent management needs. They need a clear overview of architecture, security controls, and key capabilities to make a build-vs-buy decision.

**Prospective Contributors** — Open-source developers or internal teams looking to understand the codebase structure and contribution areas before engaging. They need enough context to understand how the platform is decomposed and where to start.

**Executive Stakeholders** — Decision-makers who need a high-level, non-technical overview of what Parthenon does and why it matters. They benefit from the polished presentation and business-level descriptions.

**Existing Users / Operators** — Teams already deploying Parthenon who want a reference walkthrough for onboarding new team members or demonstrating the platform to peers.

---

## User Stories

- As a **platform evaluator**, I want to see a clear high-level architecture overview of Parthenon so that I can quickly assess whether it fits my enterprise requirements.
- As a **platform evaluator**, I want to understand the security model — including how tools permissions are controlled and how agent identities are isolated — so that I can evaluate compliance and trust boundaries.
- As a **prospective contributor**, I want to see how the three backend services are separated and what each one is responsible for so that I can identify where to contribute.
- As an **executive stakeholder**, I want to see a polished, navigable presentation of the platform's capabilities so that I can share it with my team as a reference.
- As an **operator**, I want a step-by-step walkthrough of key workflows — integrating an MCP server, creating skills and SOPs, defining agent roles, and running agents — so that I can onboard new team members efficiently.
- As any **site visitor**, I want clearly labeled placeholder images where live screenshots would appear so that I understand what a real deployment would look like and know I can substitute real screenshots.

---

## Acceptance Criteria

### Site Publishing
- The site is accessible at the project's GitHub Pages URL after merging to the main branch.
- A GitHub Actions workflow automatically builds and publishes the site on every push to main.
- The site loads correctly in modern browsers (Chrome, Firefox, Safari, Edge) without errors.

### High-Level Design Section
- The site includes a dedicated section explaining the SOP/Skill-driven MCP integration architecture.
- The site explains the tools permission control system — how tool access is granted through skills, roles, and agent identities — in business-readable language.
- The site clearly communicates the three-service backend decomposition: Control Center, Communication Hub, and Agent Runtime — and the responsibility of each.
- The site explains the dual-identity model: human realm and agent realm, including what each realm is and why the separation matters.
- All diagrams in this section are rendered from source — no external image dependencies for architectural diagrams.

### Demo / Walkthrough Section
- The site includes a dedicated demo/walkthrough section with the following distinct pages or slides:
  1. Integrating an MCP server
  2. Creating Skills and SOPs
  3. Creating Agent Roles
  4. Creating Agent Types and triggering agents (both non-conversational and conversational modes)
  5. Viewing execution logs
- Each walkthrough page describes the workflow steps in logical order, oriented toward what the user does and why.
- Where live screenshots are referenced, clearly labeled placeholder images are used (e.g., annotated boxes with descriptive captions).

### Presentation Quality
- The site uses a modern, polished visual design appropriate for a professional project showcase.
- The site is fully navigable without a backend — it is purely static HTML/CSS/JS.
- The site is responsive and readable on both desktop and mobile screen sizes.
- No broken links or missing assets are present on any page.

### Build & Deployment
- If a build step is required, the GitHub Actions workflow handles it automatically.
- The build produces a static output folder that GitHub Pages can serve directly.
- The site requires no server-side runtime or dynamic backend.

---

## Out of Scope

- Live demo environment or embedded live API access — the site is purely informational and static.
- User authentication, login, or any interactive features requiring a backend.
- Automated screenshot capture from a running Parthenon instance — screenshots are manual placeholders only.
- Documentation for contributors (API references, developer guides) — those remain in the repository's existing docs.
- Multi-language or i18n support for the showcase site.
- Search functionality.

---

## Dependencies & Constraints

- The site must be deployable via GitHub Pages and compatible with its static hosting constraints (no server-side execution).
- Placeholder images must be clearly distinguishable from real screenshots so reviewers and visitors are not misled.
- The GitHub Actions workflow must use only standard GitHub-provided runners with no external secrets required for the basic build and publish step.
- Architecture diagrams must accurately reflect the platform's three-service decomposition and security model as documented in the master architecture docs — the showcase must not contradict the actual system design.
- The chosen presentation approach (slide-deck vs. landing page) must be agreed upon before implementation begins; this PRD leaves the final format as an open question (see below).

---

## Open Questions

1. **Presentation format**: Should the site use a reveal.js slide-deck feel throughout, or a landing page with linked detail pages? The user indicated either is acceptable — the developer agent should confirm before building.
2. **Domain / subdomain**: Will the site use the default `<org>.github.io/<repo>` path or a custom domain? This affects relative URL configuration.
3. **Placeholder image convention**: Should placeholders be styled graphics with captions, simple bordered containers, or a third-party placeholder service? Using a third-party service introduces an external dependency.
