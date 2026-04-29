import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Container,
  Paper,
  Step,
  StepLabel,
  Stepper,
  Typography,
} from '@mui/material'
import axios from 'axios'
import { ProviderType, type ProviderSetupRequest, type ProviderSetupResult } from '../../types/setup'
import { postSetupIdentity } from '../../api/setupApi'
import { ProviderSelectionStep } from './ProviderSelectionStep'
import { KeycloakConfigStep } from './KeycloakConfigStep'
import { ExternalOidcConfigStep } from './ExternalOidcConfigStep'
import { VerificationStep } from './VerificationStep'
import { CompletionStep } from './CompletionStep'

/** Wizard step indices */
const STEP_PROVIDER = 0
const STEP_CONFIG = 1
const STEP_VERIFICATION = 2
const STEP_COMPLETE = 3

function useKeycloakProvider(provider: ProviderType): boolean {
  return provider === ProviderType.KEYCLOAK_BUNDLED || provider === ProviderType.KEYCLOAK_EXTERNAL
}

/**
 * SetupWizard — 4-step wizard orchestrating provider selection, configuration,
 * provisioning, and completion.
 *
 * Step 0: ProviderSelectionStep
 * Step 1: KeycloakConfigStep OR ExternalOidcConfigStep
 * Step 2: VerificationStep (spinner + result)
 * Step 3: CompletionStep
 */
export function SetupWizard() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [activeStep, setActiveStep] = useState(STEP_PROVIDER)
  const [selectedProvider, setSelectedProvider] = useState<ProviderType>(
    ProviderType.KEYCLOAK_BUNDLED,
  )
  const [formData, setFormData] = useState<Partial<ProviderSetupRequest>>({})
  const [isLoading, setIsLoading] = useState(false)
  const [result, setResult] = useState<ProviderSetupResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const isKeycloak = useKeycloakProvider(selectedProvider)

  const configStepLabel = isKeycloak
    ? t('setup.step.keycloakConfig.label')
    : t('setup.step.externalOidc.label')

  const STEPS = [
    t('setup.step.providerSelection.label'),
    configStepLabel,
    t('setup.step.verification.label'),
    t('setup.step.completion.label'),
  ]

  const handleFormChange = (updates: Partial<ProviderSetupRequest>) => {
    setFormData((prev) => ({ ...prev, ...updates }))
  }

  const handleNext = () => {
    setActiveStep((s) => s + 1)
  }

  const handleBack = () => {
    setActiveStep((s) => s - 1)
  }

  const handleSubmit = async () => {
    setActiveStep(STEP_VERIFICATION)
    setIsLoading(true)
    setError(null)
    setResult(null)

    const request: ProviderSetupRequest = {
      provider_type: selectedProvider,
      ...formData,
    }

    try {
      const res = await postSetupIdentity(request)
      setResult(res)
      if (res.success) {
        setActiveStep(STEP_COMPLETE)
      }
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        const status = err.response?.status
        if (status === 409) {
          setError(t('setup.error.alreadyConfigured'))
        } else if (status === 502) {
          setError(t('setup.error.keycloakUnreachable'))
        } else {
          const detail = err.response?.data?.detail
          setError(typeof detail === 'string' ? detail : JSON.stringify(detail))
        }
      } else {
        setError(String(err))
      }
    } finally {
      setIsLoading(false)
    }
  }

  const handleRetry = () => {
    setActiveStep(STEP_CONFIG)
    setResult(null)
    setError(null)
  }

  const handleGoToLogin = () => {
    navigate('/login', { replace: true })
  }

  const isConfigStepValid = (): boolean => {
    if (isKeycloak) {
      return Boolean(
        formData.keycloak_url &&
          formData.realm_name &&
          formData.client_id &&
          formData.admin_user &&
          formData.admin_password,
      )
    }
    return Boolean(formData.oidc_discovery_url && formData.client_id)
  }

  return (
    <Container maxWidth="sm" sx={{ mt: 8 }}>
      <Paper elevation={3} sx={{ p: 4 }}>
        <Typography variant="h5" fontWeight={700} mb={3}>
          {t('setup.title')}
        </Typography>

        <Stepper activeStep={activeStep} alternativeLabel sx={{ mb: 4 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {/* Step 0: Provider selection */}
        {activeStep === STEP_PROVIDER && (
          <ProviderSelectionStep
            selectedProvider={selectedProvider}
            onChange={(p) => {
              setSelectedProvider(p)
              setFormData({})
            }}
          />
        )}

        {/* Step 1: Config form */}
        {activeStep === STEP_CONFIG && (
          isKeycloak ? (
            <KeycloakConfigStep formData={formData} onChange={handleFormChange} />
          ) : (
            <ExternalOidcConfigStep formData={formData} onChange={handleFormChange} />
          )
        )}

        {/* Step 2: Verification */}
        {activeStep === STEP_VERIFICATION && (
          <VerificationStep isLoading={isLoading} result={result} error={error} />
        )}

        {/* Step 3: Completion */}
        {activeStep === STEP_COMPLETE && <CompletionStep onGoToLogin={handleGoToLogin} />}

        {/* Navigation buttons */}
        {activeStep !== STEP_COMPLETE && (
          <Box display="flex" justifyContent="space-between" mt={4}>
            <Button
              disabled={activeStep === STEP_PROVIDER || activeStep === STEP_VERIFICATION}
              onClick={activeStep === STEP_VERIFICATION ? handleRetry : handleBack}
            >
              {activeStep === STEP_VERIFICATION && !isLoading
                ? t('setup.action.retry')
                : t('setup.action.back')}
            </Button>

            {activeStep === STEP_PROVIDER && (
              <Button variant="contained" onClick={handleNext}>
                {t('setup.action.next')}
              </Button>
            )}

            {activeStep === STEP_CONFIG && (
              <Button
                variant="contained"
                onClick={handleSubmit}
                disabled={!isConfigStepValid()}
              >
                {t('setup.action.submit')}
              </Button>
            )}

            {activeStep === STEP_VERIFICATION && !isLoading && (error || (result && !result.success)) && (
              <Button variant="outlined" onClick={handleRetry}>
                {t('setup.action.retry')}
              </Button>
            )}
          </Box>
        )}
      </Paper>
    </Container>
  )
}
