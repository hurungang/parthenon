# Apply Material Theme — Implementation Plan

## Overview

This change applies a modern, refined Material UI theme to the Parthenon frontend, replacing the default MUI styles with a polished indigo/slate palette, Inter typography, and professional component overrides. All work is confined to `frontend/src/` — no backend changes are required. Implementation is organized in four phases: theme file creation, provider wiring, layout shell alignment, and visual verification.

## Task Checklist

### Phase 1 — Theme Configuration

- [x] 1.1 — Install Inter font package
- [x] 1.2 — Create theme directory structure
- [x] 1.3 — Define color palette tokens
- [x] 1.4 — Define typography scale with Inter
- [x] 1.5 — Define refined shadow levels
- [x] 1.6 — Define MUI component overrides
- [x] 1.7 — Compose and export complete theme

### Phase 2 — Theme Provider Setup

- [x] 2.1 — Wire ThemeProvider into application entry point
- [x] 2.2 — Update global CSS baseline

### Phase 3 — AppShell Layout Alignment

- [x] 3.1 — Restyle AppBar to white surface with bottom border
- [x] 3.2 — Restyle sidebar drawer to match prototype layout
- [x] 3.3 — Apply active/hover nav item styling via theme tokens

### Phase 4 — Testing & Polish

- [x] 4.1 — Visual review across all application pages
- [x] 4.2 — Verify colour contrast meets accessibility standards
- [x] 4.3 — Confirm no hardcoded colour values remain in component files
- [x] 4.4 — Run TypeScript type check and ESLint

---

## Phase 1 — Theme Configuration

### 1.1 — Install Inter font package

Install `@fontsource/inter` as a production dependency so Inter loads from the local bundle rather than an external CDN at runtime.

**Done when:** `@fontsource/inter` appears in `frontend/package.json` dependencies and the import resolves without error.

---

### 1.2 — Create theme directory structure

Create the directory `frontend/src/theme/` and add five files:
- `palette.ts`
- `typography.ts`
- `shadows.ts`
- `components.ts`
- `index.ts`

**Done when:** All five files exist under `frontend/src/theme/` and are importable TypeScript modules.

---

### 1.3 — Define color palette tokens

Populate `frontend/src/theme/palette.ts` with the full color map derived from the prototype:

| Token | Value | Usage |
|-------|-------|-------|
| primary.main | `#4f46e5` | Buttons, active nav, links |
| primary.dark | `#4338ca` | Hover state for primary |
| primary.light | `#e0e7ff` | Nav highlight bg, icon wrappers |
| secondary.main | `#10b981` | Success/trend indicators |
| error.main | `#ef4444` | Error, downward trend |
| warning.main | `#d97706` | Warning badges |
| background.default | `#f8fafc` | App background |
| background.paper | `#ffffff` | Cards, sidebar, topbar |
| text.primary | `#0f172a` | Main content text |
| text.secondary | `#64748b` | Labels, subtitles, secondary info |
| divider | `#e2e8f0` | All border/divider lines |

**Done when:** `palette.ts` exports a valid MUI `PaletteOptions` object with all tokens above.

---

### 1.4 — Define typography scale with Inter

Populate `frontend/src/theme/typography.ts` with:
- `fontFamily`: `'Inter', sans-serif`
- Font weights mapped to MUI variants:
  - `h1`–`h4`: weight 700, negative letter-spacing (`-0.5px` to `-1px`)
  - `h5`–`h6`: weight 600
  - `subtitle1`: weight 600, size 16px
  - `subtitle2`: weight 600, size 13px, uppercase, letter-spacing 0.5px (table headers)
  - `body1`: weight 400, size 14px
  - `body2`: weight 400, size 13px
  - `button`: weight 500, size 14px

**Done when:** `typography.ts` exports a valid MUI `TypographyOptions` object and Inter renders in the browser via the `@fontsource/inter` import.

---

### 1.5 — Define refined shadow levels

Populate `frontend/src/theme/shadows.ts` with a 25-element MUI shadow array where:
- Index 0: `'none'`
- Index 1 (sm): `'0 1px 2px 0 rgb(0 0 0 / 0.05)'`
- Index 2 (md): `'0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)'`
- Index 3 (lg): `'0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)'`
- Indices 4–24: repeat index 3 (for MUI compatibility)

**Done when:** `shadows.ts` exports a typed `Shadows` array of length 25 with no TypeScript errors.

---

### 1.6 — Define MUI component overrides

Populate `frontend/src/theme/components.ts` with `MuiComponents` overrides:

| Component | Override |
|-----------|----------|
| `MuiCard` | `borderRadius: 12`, shadow index 1, `border: '1px solid #e2e8f0'` |
| `MuiPaper` | `borderRadius: 12`, shadow index 1 |
| `MuiButton` | `borderRadius: 8`, `textTransform: 'none'`, `fontWeight: 500` |
| `MuiChip` | `borderRadius: 12`, `fontWeight: 600`, `fontSize: 12` |
| `MuiListItemButton` | `borderRadius: 8`; hover and selected: `backgroundColor: primary.light`, `color: primary.main` |
| `MuiAppBar` | `backgroundColor: background.paper`, `color: text.primary`, `boxShadow: 'none'`, `borderBottom: '1px solid #e2e8f0'` |
| `MuiDrawer` paper | `borderRight: '1px solid #e2e8f0'`, `boxShadow: 'none'` |
| `MuiAvatar` | `backgroundColor: primary.main`, `fontWeight: 600` |
| `MuiTableCell` (head) | `fontWeight: 600`, `fontSize: 13`, `textTransform: 'uppercase'`, `letterSpacing: '0.5px'`, `borderBottom: '2px solid #e2e8f0'` |
| `MuiTableRow` (body hover) | `backgroundColor: background.default` |

**Done when:** `components.ts` exports a valid `Components<Theme>` object with no TypeScript errors.

---

### 1.7 — Compose and export complete theme

Populate `frontend/src/theme/index.ts` to call `createTheme()` assembling palette, typography, shadows, and components into a single named export `parthenon`.

**Done when:** `import { parthenon } from './theme'` resolves in `main.tsx` and the app renders without console errors.

---

## Phase 2 — Theme Provider Setup

### 2.1 — Wire ThemeProvider into application entry point

Update `frontend/src/main.tsx` to:
1. Import `ThemeProvider` and `CssBaseline` from `@mui/material`
2. Import the `parthenon` theme from `./theme`
3. Wrap the root render tree with `<ThemeProvider theme={parthenon}><CssBaseline />{...}</ThemeProvider>`

`ThemeProvider` must be the outermost wrapper so all MUI components consume the theme, including those inside `AuthProvider` and `QueryClientProvider`.

**Done when:** The app renders with the indigo primary colour visible in the nav, and no MUI theme-related console errors appear.

---

### 2.2 — Update global CSS baseline

Update `frontend/src/styles/index.css` to:
- Remove the legacy `font-family` stack from the `body` rule (MUI `CssBaseline` + theme typography controls it)
- Retain only the `#root` height/flex rules

**Done when:** `index.css` no longer contains `-apple-system`, `Roboto`, or any other legacy font-family declarations.

---

## Phase 3 — AppShell Layout Alignment

### 3.1 — Restyle AppBar to white surface with bottom border

In `frontend/src/app/AppShell.tsx`, update the `<AppBar>` component:
- Remove `elevation={1}` (the component override in Phase 1.6 controls shadow and border)
- Set Toolbar `minHeight` to 72px via `sx` to match prototype topbar height

**Done when:** The AppBar renders white with a bottom border, no shadow, and a 72px height.

---

### 3.2 — Restyle sidebar drawer to match prototype layout

In `frontend/src/app/AppShell.tsx`:
- Change `DRAWER_WIDTH` from `240` to `260`
- Apply `padding: '24px 16px'` to the nav `<List>` container via `sx`
- Wrap the brand/title in the `<Toolbar>` with `padding: '24px'` and add a `<Divider>` below it

The `MuiDrawer` component override from Phase 1.6 removes the shadow and sets the right border.

**Done when:** Sidebar renders at 260px, white background, right-border only, with 24px logo padding.

---

### 3.3 — Apply active/hover nav item styling via theme tokens

In `frontend/src/app/AppShell.tsx`, the `<ListItemButton>` `selected` prop already drives active state. Verify the `MuiListItemButton` override from Phase 1.6 correctly applies hover and selected colours. Remove any inline `sx` colour overrides on `ListItemButton` that conflict with the theme-level override.

**Done when:** Active and hovered nav items show the indigo highlight background with no inline `sx` colour overrides on the button.

---

## Phase 4 — Testing & Polish

### 4.1 — Visual review across all application pages

Open each major page (Dashboard, MCP Hub, Skills, Agents, Gateway, Schedules, Conversations, Results, Notifications, Observability, Permissions) and verify:
- Cards use 12px border-radius, shadow index 1, and a 1px slate border
- Typography renders in Inter at correct weights
- Buttons, Chips, and Badges match the prototype palette
- Page background is `#f8fafc`, card backgrounds are `#ffffff`

**Done when:** All pages visually match the prototype aesthetic with no obvious style regressions.

---

### 4.2 — Verify colour contrast meets accessibility standards

Check foreground/background combinations for WCAG AA compliance (4.5:1 for normal text):
- `text.primary (#0f172a)` on `background.default (#f8fafc)` — verify passes
- `text.secondary (#64748b)` on `background.paper (#ffffff)` — verify passes
- `#ffffff` on `primary.main (#4f46e5)` for buttons — verify passes

Flag any combination below 4.5:1 and adjust the token value in `palette.ts`.

**Done when:** All major text/background combinations pass WCAG AA.

---

### 4.3 — Confirm no hardcoded colour values remain in component files

Search `frontend/src/` for raw hex colour strings in `.tsx`/`.ts` files outside `frontend/src/theme/`. Any occurrence must be replaced with a `theme.palette.*` reference or `sx` colour token.

**Done when:** Grep returns zero hex colour literals in component/page files outside the `theme/` directory.

---

### 4.4 — Run TypeScript type check and ESLint

Run `tsc --noEmit` and `eslint src/` from `frontend/`. Resolve any type errors or lint warnings introduced by the theme files.

**Done when:** Both commands exit with zero errors.

---

## Completion Checklist

- [x] `frontend/src/theme/` directory contains all five files (palette, typography, shadows, components, index)
- [x] `@fontsource/inter` is installed and imported in the theme
- [x] `ThemeProvider` wraps the application root in `main.tsx`
- [x] `CssBaseline` is included inside `ThemeProvider`
- [x] Global `index.css` no longer contains legacy font-family declarations
- [x] `AppShell` sidebar width is 260px
- [x] `AppShell` AppBar renders without elevation shadow, with bottom border
- [x] Nav item active/hover state uses indigo highlight from theme tokens only (no inline `sx` colour overrides)
- [x] All pages visually reviewed and consistent with prototype
- [x] No hardcoded hex colour values in component files
- [x] TypeScript type check and ESLint pass with zero errors
