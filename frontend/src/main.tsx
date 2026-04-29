import React from 'react'
import ReactDOM from 'react-dom/client'
import { ThemeProvider } from '@mui/material/styles'
import CssBaseline from '@mui/material/CssBaseline'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { I18nextProvider } from 'react-i18next'
import i18n from './i18n/config'
import { AuthProvider } from './stores/AuthContext'
import { AppRouter } from './app/AppRouter'
import { initTelemetry } from './telemetry'
import { fetchTelemetryConfig } from './api/telemetryApi'
import { parthenon } from './theme'
import './styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000, // 1 minute
      retry: 1,
    },
  },
})

// Bootstrap telemetry before rendering — fetch config from backend then initialise.
// Failure is graceful: fetchTelemetryConfig() never throws and returns safe defaults.
fetchTelemetryConfig().then((config) => {
  initTelemetry(config)
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider theme={parthenon}>
      <CssBaseline />
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <AppRouter />
          </AuthProvider>
        </QueryClientProvider>
      </I18nextProvider>
    </ThemeProvider>
  </React.StrictMode>,
)
