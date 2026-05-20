# Frontend — React SPA

The Parthenon frontend is a Vite + React 19 + TypeScript SPA with MUI 7 and React Router 7.

Contributors working in this package must follow the repository CLA flow before
their pull requests can be merged. See [../CLA.md](../CLA.md) and
[../CONTRIBUTING.md](../CONTRIBUTING.md).

## Structure

```
frontend/
├── src/
│   ├── api/            # axios apiClient
│   ├── app/            # AppRouter, AppShell
│   ├── stores/         # AuthContext, useAuthStore
│   ├── pages/          # Page components
│   ├── hooks/          # Custom React hooks
│   └── components/     # Shared UI components
└── public/             # Static assets
```
