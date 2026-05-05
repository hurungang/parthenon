import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from '@mui/material'
import LoginIcon from '@mui/icons-material/Login'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentIdentity } from '../../types'

interface AgentIdentityDialogProps {
  open: boolean
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Create dialog for AgentIdentity via OAuth.
 *
 * Shows a "Sign In as Agent" button that initiates the OAuth authorization
 * code flow against the configured agent realm. When OAuth completes, the
 * backend automatically creates the AgentIdentity record with stored tokens.
 *
 * Realm name comes from bootstrap config (identity.yaml), not user input.
 *
 * Follows the Dialog Error Handling Standard.
 */
export function AgentIdentityDialog({
  open,
  onClose,
  onSaved,
}: AgentIdentityDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [oauthInitiating, setOauthInitiating] = useState(false)
  const popupRef = useRef<Window | null>(null)
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (open) {
      setDialogError(null)
      setOauthInitiating(false)
    }
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
      if (popupRef.current && !popupRef.current.closed) popupRef.current.close()
    }
  }, [open])

  const handleOAuthSignIn = async () => {
    try {
      setDialogError(null)
      setOauthInitiating(true)

      // Get authorization URL from backend
      const { data } = await apiClient.get<{ authorization_url: string }>(
        '/agents/identities/oauth/authorize',
      )

      // Open the authorization URL in a popup window
      const popup = window.open(
        data.authorization_url,
        'agentOAuth',
        'width=600,height=700,menubar=no,toolbar=no,location=yes,status=no',
      )
      popupRef.current = popup

      // Listen for postMessage from the callback page
      const messageHandler = async (event: MessageEvent) => {
        if (event.origin !== window.location.origin) return
        if (event.data?.type === 'AGENT_OAUTH_SUCCESS') {
          window.removeEventListener('message', messageHandler)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
          setOauthInitiating(false)
          await onSaved()
          onClose() // Close dialog after successful creation
        } else if (event.data?.type === 'AGENT_OAUTH_ERROR') {
          window.removeEventListener('message', messageHandler)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
          setOauthInitiating(false)
          const desc = event.data.errorDescription ?? event.data.error ?? 'OAuth sign-in failed'
          setDialogError(new Error(desc))
        }
      }
      window.addEventListener('message', messageHandler)

      // Fallback: also poll for popup closure in case the callback page doesn't postMessage
      pollIntervalRef.current = setInterval(() => {
        if (popup && popup.closed) {
          window.removeEventListener('message', messageHandler)
          if (pollIntervalRef.current) clearInterval(pollIntervalRef.current)
          setOauthInitiating(false)
        }
      }, 500)
    } catch (err) {
      setOauthInitiating(false)
      setDialogError(err)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => { onClose(); setDialogError(null) }}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>{t('agents.identities.createTitle')}</DialogTitle>

      <DialogContent dividers>
        {dialogError && (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        )}

        <Box display="flex" flexDirection="column" gap={2} pt={1}>
          <Typography variant="body2" color="text.secondary">
            {t('agents.identities.oauthInstructions')}
          </Typography>

          <Button
            variant="contained"
            startIcon={<LoginIcon />}
            onClick={handleOAuthSignIn}
            disabled={oauthInitiating}
            size="large"
          >
            {oauthInitiating
              ? t('agents.identities.oauthPending')
              : t('agents.identities.signInAsAgent')}
          </Button>

          <Typography variant="caption" color="text.secondary">
            {t('agents.identities.oauthNote')}
          </Typography>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }}>
          {t('app.cancel')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
