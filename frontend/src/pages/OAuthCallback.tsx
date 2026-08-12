import { useEffect } from 'react'
import { Box, CircularProgress, Typography } from '@mui/material'
import apiClient from '../api/apiClient'

export default function OAuthCallback() {
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const code = params.get('code')
    const state = params.get('state')
    const error = params.get('error')

    const handleCallback = async () => {
      if (error) {
        // Send error back to parent
        if (window.opener) {
          window.opener.postMessage(
            { type: 'MCP_OAUTH_ERROR', error, errorDescription: params.get('error_description') },
            window.location.origin
          )
        }
        window.close()
        return
      }

      if (code && state) {
        try {
          // Call backend to exchange code for tokens
          const { data } = await apiClient.get('/mcp/oauth/callback', {
            params: { code, state }
          })
          
          // Send success back to parent window with session ID
          if (window.opener) {
            window.opener.postMessage(
              { type: 'MCP_OAUTH_SUCCESS', sessionId: data.session_id },
              window.location.origin
            )
          }
          
          // Close popup after a brief delay
          setTimeout(() => window.close(), 500)
        } catch (err: any) {
          // Send error back to parent
          if (window.opener) {
            window.opener.postMessage(
              { type: 'MCP_OAUTH_ERROR', error: 'token_exchange_failed', errorDescription: err.message },
              window.location.origin
            )
          }
          window.close()
        }
      }
    }

    handleCallback()
  }, [])

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
      <Typography variant="body1">Completing OAuth authentication...</Typography>
    </Box>
  )
}
