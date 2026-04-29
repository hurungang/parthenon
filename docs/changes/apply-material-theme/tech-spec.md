# Apply Material Theme — Technical Specification

## Technical Overview

The theming change introduces a centralized MUI theme built from five dedicated modules under `frontend/src/theme/` and provided to the entire React tree via MUI's `ThemeProvider`. The theme uses a modern indigo/slate color palette, Inter typography with a refined weight hierarchy, polished card shadows, and targeted component overrides — all derived from the revised prototype. No backend changes or new runtime state are required.

## Component Breakdown

| Area | File | Change Type |
|------|------|-------------|
| Color palette | `frontend/src/theme/palette.ts` | New file |
| Typography | `frontend/src/theme/typography.ts` | New file |
| Shadow levels | `frontend/src/theme/shadows.ts` | New file |
| Component overrides | `frontend/src/theme/components.ts` | New file |
| Theme composition | `frontend/src/theme/index.ts` | New file |
| App bootstrap | `frontend/src/main.tsx` | Add ThemeProvider + CssBaseline |
| Global CSS | `frontend/src/styles/index.css` | Remove legacy font-family stack |
| Layout shell | `frontend/src/app/AppShell.tsx` | DRAWER_WIDTH 240→260, AppBar white surface, nav active state |

## Theme Structure

The theme is split across four feature modules assembled in `index.ts`.

### Palette

Defines semantic color roles matching the prototype's CSS variable tokens:

| Token | Value | Usage |
|-------|-------|-------|
| `primary.main` | `#4f46e5` | Buttons, active nav, focus rings |
| `primary.dark` | `#4338ca` | Hover state on primary elements |
| `primary.light` | `#e0e7ff` | Nav highlight background, icon wrapper fills |
| `secondary.main` | `#10b981` | Success states, upward trend indicators |
| `error.main` | `#ef4444` | Error states, downward trend indicators |
| `warning.main` | `#d97706` | Warning badges |
| `background.default` | `#f8fafc` | Application canvas |
| `background.paper` | `#ffffff` | Cards, sidebar, topbar |
| `text.primary` | `#0f172a` | Main body and heading text |
| `text.secondary` | `#64748b` | Labels, subtitles, helper text |
| `divider` | `#e2e8f0` | Borders, table lines, drawer separators |

### Typography

- `fontFamily`: `'Inter', sans-serif` (loaded from `@fontsource/inter`)
- Weight hierarchy: 300 (light) / 400 (regular) / 500 (medium) / 600 (semibold) / 700 (bold)
- Heading variants (`h1`–`h4`): weight 700, negative letter-spacing for tighter optical fit
- Section titles (`h5`, `h6`): weight 600
- Table column headers (`subtitle2`): weight 600, uppercase, letter-spacing 0.5px
- Body text: weight 400, 14px base size
- Button labels: weight 500, `textTransform: none`

### Shadows

A 25-element `Shadows` array replacing MUI defaults:

| Index | Label | Value |
|-------|-------|-------|
| 0 | none | `'none'` |
| 1 | sm | `'0 1px 2px 0 rgb(0 0 0 / 0.05)'` |
| 2 | md | `'0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)'` |
| 3–24 | lg | `'0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)'` |

Cards rest on shadow index 1 at rest and elevate to index 2 on hover.

### Component Overrides

Targeted style overrides applied globally through the MUI component system:

| Component | Key Overrides |
|-----------|---------------|
| `MuiCard` | `borderRadius: 12`, shadow index 1, `border: '1px solid #e2e8f0'` |
| `MuiPaper` | `borderRadius: 12`, shadow index 1 |
| `MuiButton` | `borderRadius: 8`, `textTransform: 'none'`, `fontWeight: 500` |
| `MuiChip` | `borderRadius: 12`, `fontWeight: 600`, `fontSize: 12` |
| `MuiListItemButton` | `borderRadius: 8`; hover/selected: `backgroundColor: primary.light`, `color: primary.main` |
| `MuiAppBar` | `backgroundColor: background.paper`, `color: text.primary`, `boxShadow: 'none'`, `borderBottom: '1px solid #e2e8f0'` |
| `MuiDrawer` paper | `borderRight: '1px solid #e2e8f0'`, `boxShadow: 'none'` |
| `MuiAvatar` | `backgroundColor: primary.main`, `fontWeight: 600` |
| `MuiTableCell` (head) | `fontWeight: 600`, `fontSize: 13`, `textTransform: 'uppercase'`, `letterSpacing: '0.5px'`, `borderBottom: '2px solid #e2e8f0'` |
| `MuiTableRow` (body) | hover: `backgroundColor: background.default` |

## State Management

No new runtime state is introduced. The theme is a static constant — dark mode and runtime theme switching are out of scope per the PRD.

`ThemeProvider` is placed as the outermost wrapper in `main.tsx` (inside `React.StrictMode`), so all MUI components throughout `I18nextProvider`, `QueryClientProvider`, and `AuthProvider` consume it. No new stores or context providers are required.

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `parthenon` | const | Composed MUI theme — palette + typography + shadows + components | `frontend/src/theme/index.ts` |
| `palette` | object | Color token definitions (indigo/slate) | `frontend/src/theme/palette.ts` |
| `typography` | object | Inter font family and weight-mapped variant scale | `frontend/src/theme/typography.ts` |
| `shadows` | array | 25-element refined shadow array | `frontend/src/theme/shadows.ts` |
| `components` | object | MUI component style overrides | `frontend/src/theme/components.ts` |
| `ThemeProvider` | component | Injects theme into React context | `frontend/src/main.tsx` |
| `CssBaseline` | component | Global CSS reset applying theme background | `frontend/src/main.tsx` |
| `AppShell` | component | Top-level layout — sidebar drawer, AppBar, page outlet | `frontend/src/app/AppShell.tsx` |
| `DRAWER_WIDTH` | const | Sidebar pixel width — updated from 240 to 260 | `frontend/src/app/AppShell.tsx` |
| `NAV_ITEMS` | const | Navigation item definitions (path, icon, i18n key) | `frontend/src/app/AppShell.tsx` |
| `index.css` | stylesheet | Global root layout rules (font-family removed) | `frontend/src/styles/index.css` |
