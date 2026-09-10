# GitHub Pages Project Showcase — Deployment

This guide documents the deployment of the Parthenon Project Showcase static site to GitHub Pages. This deployment is **completely independent** of the main Parthenon application stack (no Docker Compose, no backend services, no database). It is a fully static Vite site built and published entirely by a GitHub Actions workflow.

---

## Deployment Target

| Attribute | Value |
|-----------|-------|
| Target | GitHub Pages |
| URL | `https://<org-or-user>.github.io/Parthenon/` |
| Custom domain | Not configured (see [Custom Domain Setup](#custom-domain-optional)) |
| Source directory | `site/` |
| Build output | `docs/site/` (at repo root) |
| Authentication | OIDC via GitHub Actions (no secrets required) |
| Workflow file | `.github/workflows/deploy-github-pages.yml` |

---

## Trigger

The deployment workflow triggers automatically on every push to `main` that includes changes under the following paths:

- `site/**` — any change to the showcase source files
- `.github/workflows/deploy-github-pages.yml` — changes to the workflow itself

Changes to other parts of the repository (backend, frontend application, documentation prose) do **not** trigger a rebuild.

The workflow at `.github/workflows/deploy-github-pages.yml` uses a `paths` filter on the `push` trigger to restrict builds to the `main` branch and the two paths above (see the workflow file for the exact `on.push.branches` / `on.push.paths` configuration).

---

## One-Time Repository Setup

These steps must be completed once by a repository administrator before the first deployment. They do not need to be repeated.

### Step 1 — Enable GitHub Pages

1. Navigate to the repository on GitHub and open **Settings**.
2. In the left sidebar, select **Pages**.
3. Under **Build and deployment**, set the **Source** to **GitHub Actions** (not "Deploy from a branch").
4. Save the setting. GitHub will display the Pages URL — typically `https://<org-or-user>.github.io/Parthenon/`. Note this URL.

### Step 2 — Verify Actions Permissions

1. Go to **Settings → Actions → General**.
2. Under **Actions permissions**, confirm **Allow all actions and reusable workflows** is selected (or at minimum, actions from GitHub are allowed).
3. Under **Workflow permissions**, ensure **Read and write permissions** is selected so the workflow-level `permissions` block (`pages: write`, `id-token: write`) takes effect.

### Step 3 — Confirm No Secrets Required

The workflow authenticates to GitHub Pages via OIDC — the `id-token: write` permission is sufficient. No repository secrets or environment variables need to be configured for this deployment.

---

## Build and Deploy Process

On each push to `main` matching the trigger paths, the workflow executes two jobs:

### Job 1 — `build`

1. Checks out the repository.
2. Sets up Node.js 20 with npm caching.
3. Runs `npm ci` inside `site/` for a clean dependency install.
4. Runs `npm run build` inside `site/`. Vite outputs the built static files to `docs/site/` (configured via `outDir: '../docs/site'` in `site/vite.config.ts`).
5. Uploads `docs/site/` as a GitHub Pages artifact using `actions/upload-pages-artifact@v3`.

### Job 2 — `deploy`

1. Picks up the Pages artifact uploaded by the `build` job.
2. Deploys it to GitHub Pages using `actions/deploy-pages@v4`.
3. The `page_url` output from the deploy step provides the live URL.

Both jobs must show green for the deployment to be considered successful. The `concurrency` setting (`group: pages`) ensures that only one deployment runs at a time, with any in-progress run cancelled when a new push arrives.

---

## Rollback Procedure

### Option A — Re-run a Previous Successful Workflow

1. On GitHub, go to **Actions** and find the `Deploy GitHub Pages` workflow.
2. Locate the last known-good workflow run (the one that deployed the version to restore).
3. Click that run and select **Re-run all jobs**.
4. GitHub Actions redeploys the artifact from that run to GitHub Pages.

> **Note:** GitHub retains workflow artifacts for 90 days by default. If the artifact for the target run has expired, use Option B.

### Option B — Revert the Commit and Push

1. Identify the commit hash of the last known-good state using `git log`.
2. Create a revert commit:
   ```powershell
   git revert <bad-commit-hash>
   ```
3. Push to `main`. This triggers a fresh build from the reverted source, producing and deploying clean output.

---

## Custom Domain (Optional)

To serve the showcase at a custom domain (e.g., `parthenon.example.com`) instead of the default `*.github.io` URL:

### Step 1 — Create the CNAME File

Create `site/public/CNAME` with the custom domain as its sole content (a single line containing the domain, e.g. `parthenon.example.com`).

Vite copies everything in `public/` verbatim into the build output, so this file will appear at the root of `docs/site/` after the build.

### Step 2 — Commit and Push

Commit the `CNAME` file and push to `main`. After the next successful deployment, GitHub Pages reads it and associates the custom domain.

### Step 3 — Configure DNS

At your DNS registrar, add a CNAME record:

| Record type | Name | Target |
|-------------|------|--------|
| CNAME | `parthenon` (or chosen subdomain) | `<org-or-user>.github.io` |

For apex domains (e.g., `example.com`), use ALIAS or ANAME records instead.

### Step 4 — Verify in Repository Settings

1. Go to **Settings → Pages**.
2. Confirm the custom domain field is populated.
3. Enable the **Enforce HTTPS** checkbox once the Let's Encrypt certificate has been provisioned (may take a few minutes after the first deploy with the CNAME).

No changes to `vite.config.ts` are needed — `base: './'` uses relative paths that work with both the default and custom domains.

---

## Independence from Main App Stack

This deployment is entirely separate from the main Parthenon platform deployment documented in the rest of this section:

- **No Docker Compose services** are involved. The `parthenon.ps1` management script does not control or interact with this deployment.
- **No backend services** (Control Center, Agent Runtime, Communication Hub) are involved.
- **No database migrations** are relevant.
- **No environment variables or secrets** in the Parthenon platform configuration apply to this deployment.
- **No identity provider or OIDC configuration** is required.

The showcase site is a client-side-only static application deployed to GitHub's infrastructure, not to the Parthenon platform infrastructure.
