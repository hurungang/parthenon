# Demo Cases: apply-material-theme
<!-- Curated representative scenarios for product demo -->
<!-- Use with: /demo-app --cases docs/changes/apply-material-theme/demo-cases.md -->

## Grep Patterns
<!-- One Playwright test title per line (must match describe + test name exactly) -->
<!-- demo-app reads these lines and joins them into a --grep regex -->
- Theme Application > Inter font is applied globally
- Component Theming > Cards have 12px border radius
- Page Consistency > Dashboard uses theme consistently
- Accessibility > Color contrast meets WCAG AA standards

## Scenario Details
| # | Feature       | What it Shows                                              | Spec File                  | Test Name                          |
|---|--------------|-----------------------------------------------------------|----------------------------|-------------------------------------|
| 1 | Global Font  | Inter font loaded and applied throughout app              | theme-application.spec.ts  | Inter font is applied globally      |
| 2 | Card Polish  | 12px border radius on cards demonstrates refined styling  | component-theming.spec.ts  | Cards have 12px border radius       |
| 3 | Page Theme   | Dashboard page shows complete theme with indigo nav and slate background | page-consistency.spec.ts   | Dashboard uses theme consistently   |
| 4 | Quality      | WCAG AA color contrast proves professional polish         | accessibility.spec.ts      | Color contrast meets WCAG AA standards |
