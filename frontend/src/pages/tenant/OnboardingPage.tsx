/**
 * OnboardingPage — guided onboarding for new tenants: connect sign-in →
 * invite users → finish.  Completion flips the tenant's ``is_onboarded``
 * flag; skipping is allowed but surfaced in the workspace.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import {
  completeOnboarding,
  createInvitation,
  getOnboardingStatus,
} from '../../api/tenantApi'

export function OnboardingPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteTokenShown, setInviteTokenShown] = useState<string | null>(null)
  const [step, setStep] = useState(0)

  const statusQuery = useQuery({
    queryKey: ['tenant', 'onboarding'],
    queryFn: getOnboardingStatus,
  })

  const inviteMutation = useMutation({
    mutationFn: () =>
      createInvitation({ email: inviteEmail.trim(), tenant_role: 'member' }),
    onSuccess: (invitation) => {
      setInviteTokenShown(invitation.accept_token)
      setInviteEmail('')
      setStep(1)
    },
    onError: (err) => setDialogError(err),
  })

  const completeMutation = useMutation({
    mutationFn: completeOnboarding,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['tenant'] })
    },
    onError: (err) => setDialogError(err),
  })

  const onboarded = statusQuery.data?.is_onboarded === true

  return (
    <Box p={3} maxWidth={720}>
      <Typography variant="h5" mb={2}>
        {t('tenant.onboarding.title')}
      </Typography>

      {onboarded && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {t('tenant.onboarding.alreadyComplete')}
        </Alert>
      )}
      {dialogError != null && (
        <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
      )}

      <Card>
        <CardContent>
          <Stepper activeStep={onboarded ? 2 : step} alternativeLabel sx={{ mb: 3 }}>
            <Step key="invite">
              <StepLabel>{t('tenant.onboarding.stepInvite')}</StepLabel>
            </Step>
            <Step key="signin">
              <StepLabel>{t('tenant.onboarding.stepSignin')}</StepLabel>
            </Step>
            <Step key="finish">
              <StepLabel>{t('tenant.onboarding.stepFinish')}</StepLabel>
            </Step>
          </Stepper>

          {!onboarded && (
            <>
              <Typography variant="body2" color="text.secondary" mb={2}>
                {t('tenant.onboarding.inviteHelp')}
              </Typography>
              <Box display="flex" gap={1} mb={2}>
                <TextField
                  size="small"
                  fullWidth
                  type="email"
                  label={t('tenant.onboarding.inviteEmail')}
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  data-testid="onboarding-invite-email"
                />
                <Button
                  variant="contained"
                  disabled={inviteMutation.isPending || !inviteEmail.trim()}
                  onClick={() => {
                    clearDialogError()
                    inviteMutation.mutate()
                  }}
                >
                  {t('tenant.onboarding.inviteSend')}
                </Button>
              </Box>
              {inviteTokenShown && (
                <Alert severity="info" sx={{ mb: 2 }}>
                  {t('tenant.onboarding.tokenNote')}
                  <Box component="code" sx={{ display: 'block', mt: 1, wordBreak: 'break-all' }}>
                    {inviteTokenShown}
                  </Box>
                </Alert>
              )}
            </>
          )}

          <Box display="flex" gap={1}>
            {!onboarded && (
              <Button
                variant="contained"
                disabled={completeMutation.isPending}
                onClick={() => {
                  clearDialogError()
                  completeMutation.mutate()
                }}
              >
                {t('tenant.onboarding.finish')}
              </Button>
            )}
            {!onboarded && (
              <Button
                onClick={() => {
                  clearDialogError()
                  completeMutation.mutate()
                }}
                color="inherit"
              >
                {t('tenant.onboarding.skip')}
              </Button>
            )}
          </Box>
          {!onboarded && (
            <Typography variant="caption" color="text.secondary" display="block" mt={1}>
              {t('tenant.onboarding.skipNote')}
            </Typography>
          )}
        </CardContent>
      </Card>
    </Box>
  )
}
