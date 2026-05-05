import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Box, CircularProgress, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import apiClient from '../../api/apiClient'
import type { AgentIdentity } from '../../types'

/**
 * OAuth callback page for agent realm sign-in.
 *
 * This page is loaded in the popup window opened by AgentIdentityDialog.
 * It reads the `code` and `state` query parameters from the URL, calls the
 * backend callback endpoint to exchange the code for tokens, then signals
 * the opener window and closes the popup.
 */
export function AgentOAuthCallbackPage() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const processed = useRef(false)

  useEffect(() => {
    if (processed.current) return
    processed.current = true

    const code = searchParams.get('code')
    const state = searchParams.get('state')
    const error = searchParams.get('error')
    const errorDescription = searchParams.get('error_description')

    if (error) {
      // IdP returned an error — signal the opener and close
      if (window.opener) {
        window.opener.postMessage(
          { type: 'AGENT_OAUTH_ERROR', error, errorDescription },
          window.location.origin,
        )
      }
      window.close()
      return
    }

    if (!code || !state) {
      if (window.opener) {
        window.opener.postMessage(
          { type: 'AGENT_OAUTH_ERROR', error: 'missing_params' },
          window.location.origin,
        )
      }
      window.close()
      return
    }

    // Call the backend to exchange the authorization code for tokens
    apiClient
      .get<AgentIdentity>(`/agents/identities/oauth/callback?code=${encodeURIComponent(code)}&state=${encodeURIComponent(state)}`)
      .then(({ data }) => {
        // Signal the opener that the flow succeeded
        if (window.opener) {
          window.opener.postMessage(
            { type: 'AGENT_OAUTH_SUCCESS', identity: data },
            window.location.origin,
          )
        }
      })
      .catch((err) => {
        const detail = err?.response?.data?.detail ?? String(err)
        if (window.opener) {
          window.opener.postMessage(
            { type: 'AGENT_OAUTH_ERROR', error: 'callback_failed', errorDescription: detail },
            window.location.origin,
          )
        }
      })
      .finally(() => {
        window.close()
      })
  }, [searchParams])

  return (
    <Box
      display="flex"
      flexDirection="column"
      alignItems="center"
      justifyContent="center"
      minHeight="100vh"
      gap={2}
    >
      <CircularProgress />
      <Typography variant="body1">{t('agents.identities.oauthPending')}</Typography>
    </Box>
  )
}
