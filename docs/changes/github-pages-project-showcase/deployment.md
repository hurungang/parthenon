# Deployment Guide: GitHub Pages Project Showcase

## Overview

The GitHub Pages Project Showcase is a fully static Vite site with no backend or server-side runtime. Deployment is handled entirely by a GitHub Actions workflow (`.github/workflows/deploy-github-pages.yml`) that builds the site from `site/` and publishes the output to GitHub Pages on every push to `main`.

No secrets or service credentials are required. The pipeline authenticates to GitHub Pages via OIDC (the `id-token: write` permission is sufficient).

---

## 1. New Environment Variables / Repository Settings

There are **no secrets or environment variables** to configure. The pipeline uses OIDC-based deployment exclusively.

The only repository-level setting required is enabling GitHub Pages itself (see Section 2 below).

---

## 2. GitHub Repository Setup Steps

These steps must be completed once by a repository administrator before the first deployment.

1. Navigate to the repository on GitHub and open **Settings**.
2. In the left sidebar, select **Pages**.
3. Under **Build and deployment**, set the **Source** to **GitHub Actions** (not "Deploy from a branch"). This is the mode that allows the Actions workflow to upload a Pages artifact directly.
4. Save the setting. GitHub will display the Pages URL that the site will be served from — typically `https://<org-or-user>.github.io/<repo-name>/`. Note this URL for DNS configuration if using a custom domain.
5. Ensure the repository's **Actions** permissions allow workflows to run. Go to **Settings → Actions → General** and confirm **Allow all actions and reusable workflows** (or at minimum allow actions from GitHub) is selected.
6. Confirm that the workflow has the required permissions. The workflow file declares `pages: write` and `id-token: write` at the job level — no additional configuration is needed in the repository if the default token permissions are not set to read-only. If they are, go to **Settings → Actions → General → Workflow permissions** and set to **Read and write permissions**, or ensure the workflow-level `permissions` block is honoured.

---

## 3. First Deployment Steps

Follow these steps in order to get the first deployment live.

1. Complete all GitHub Repository Setup Steps in Section 2.
2. Ensure the `site/` directory and all source files specified in `tech-spec.md` are committed to the `main` branch, including `.github/workflows/deploy-github-pages.yml`.
3. Verify that `site/vite.config.ts` has `base` set to `'./'` and `build.outDir` set to `'../docs'`. This ensures the Vite output lands in `docs/` at the repo root, which is the artifact path the workflow uploads.
4. Push all commits to `main`. The push triggers the `deploy-github-pages` workflow automatically.
5. Open the repository on GitHub and navigate to **Actions**. Find the `deploy-github-pages` workflow run triggered by the push.
6. Watch the `build` job complete — it runs `npm ci` then `npm run build` inside `site/`, producing the `docs/` output, then uploads it as a Pages artifact.
7. Watch the `deploy` job complete — it picks up the artifact and deploys it to GitHub Pages.
8. Once both jobs show green, open the Pages URL noted in Section 2 Step 4 to confirm the site is live.
9. Verify the Mermaid architecture diagram renders correctly and tab switching works in the browser.

---

## 4. Ongoing Deployment

After the first deployment, all subsequent deployments are fully automatic.

- Any push to the `main` branch that includes changes to files under `site/**` triggers the `deploy-github-pages` workflow.
- Changes to other parts of the repository (backend, frontend application, docs prose) do **not** trigger a rebuild, because the workflow uses a `paths: site/**` filter on the push trigger.
- The workflow runs `npm ci` (clean install) and `npm run build` on every triggered run, so the `docs/` output is always produced from a clean state.
- No manual steps are required after the initial setup.

---

## 5. Rollback Procedure

### Option A — Re-run a previous successful workflow

1. On GitHub, go to **Actions** and find the `deploy-github-pages` workflow.
2. Locate the last known-good workflow run (the one that deployed the version you want to restore).
3. Click that run and select **Re-run all jobs** (or **Re-run failed jobs** if only deploy failed).
4. GitHub Actions will redeploy the artifact from that run to GitHub Pages.

Note: GitHub retains workflow artifacts for 90 days by default. If the artifact for that run has expired, use Option B.

### Option B — Revert the commit and push

1. Identify the commit hash of the last known-good state using `git log`.
2. Create a revert commit or reset to that commit on a local branch.
3. Push to `main`. This triggers a fresh build from the reverted source, producing and deploying clean output.

---

## 6. Custom Domain (Optional)

If you want to serve the showcase at a custom domain (e.g., `parthenon.example.com`) instead of the default `*.github.io` URL:

1. Create a file named `CNAME` (no extension) in the `site/public/` directory. Its sole content should be the custom domain name, for example: `parthenon.example.com`. Vite copies everything in `public/` verbatim into the build output, so the `CNAME` file will appear at the root of `docs/` after the build.
2. Commit and push the `CNAME` file to `main`. After the next successful deployment, GitHub Pages will read it and associate the custom domain.
3. At your DNS registrar, add a CNAME record pointing `parthenon.example.com` (or your chosen subdomain) to `<org-or-user>.github.io`. For apex domains (e.g., `example.com`) use ALIAS or ANAME records instead, pointing to `<org-or-user>.github.io`.
4. In the repository **Settings → Pages**, confirm that the custom domain field is populated and that the **Enforce HTTPS** checkbox is enabled once the certificate has been provisioned (GitHub provisions a Let's Encrypt certificate automatically, which may take a few minutes).
5. After DNS propagation (which can take up to 24–48 hours), verify the site is accessible at the custom domain with HTTPS.

No changes to `vite.config.ts` are needed when switching to a custom domain because `base: './'` uses relative paths throughout.

---

## 7. Master Documentation to Update

After the first successful deployment, update the following master documentation:

- **`docs/master/deployment/`** — Add a new section or file (e.g., `github-pages-showcase.md`) documenting:
  - The GitHub Pages URL and any custom domain
  - How to trigger a deployment (push to main with changes under `site/`)
  - The rollback procedure (Sections 5A and 5B above)
  - A note that this deployment is independent of the main Parthenon application stack (no Docker Compose involvement, no backend services)
- If a custom domain is configured, record the DNS record type and target value for future reference by operators who may manage DNS for this repository.
