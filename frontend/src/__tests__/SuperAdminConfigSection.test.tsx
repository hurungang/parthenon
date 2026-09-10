import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import React from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { SuperAdminConfigSection } from '../components/system/SuperAdminConfigSection'

// Mock i18next
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}))

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('SuperAdminConfigSection', () => {
  const enabledStatus = {
    is_enabled: true,
    username: 'admin',
    env_controlled: false,
  }

  const disabledStatus = {
    is_enabled: false,
    username: 'admin',
    env_controlled: false,
  }

  const envControlledStatus = {
    is_enabled: true,
    username: 'admin',
    env_controlled: true,
  }

  it('renders the title', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.title')).toBeDefined()
  })

  it('shows Enabled chip when enabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('Enabled')).toBeDefined()
  })

  it('shows Disabled chip when disabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: disabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('Disabled')).toBeDefined()
  })

  it('shows username in status', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('admin')).toBeDefined()
  })

  it('shows placeholder when username is null', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: { is_enabled: false, username: null, env_controlled: false },
    }), { wrapper: Wrapper })
    expect(screen.getByText('app.noData')).toBeDefined()
  })

  it('shows env-controlled alert when env_controlled is true', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: envControlledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.envControlled')).toBeDefined()
  })

  it('shows enable description alert when enabled and not env-controlled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: enabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.enableDescription')).toBeDefined()
  })

  it('shows disabled-by-env alert when disabled', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: disabledStatus,
    }), { wrapper: Wrapper })
    expect(screen.getByText('systemConfig.superAdmin.disabledByEnv')).toBeDefined()
  })

  it('renders without status (null)', () => {
    render(React.createElement(SuperAdminConfigSection, {
      status: null,
    }), { wrapper: Wrapper })
    expect(screen.getByText('Disabled')).toBeDefined()
  })
})
