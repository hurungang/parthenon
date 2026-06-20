import { Box, Button, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'

// ── Props ─────────────────────────────────────────────────────────────────────

interface InterventionPendingBannerProps {
  pending: boolean
  subAgentName: string
  interventionType: string
  pendingSince: string
  onRespond: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export function InterventionPendingBanner({
  pending,
  subAgentName,
  interventionType,
  pendingSince,
  onRespond,
}: InterventionPendingBannerProps) {
  const { t } = useTranslation()

  if (!pending) {
    return null
  }

  const typeLabel = (type: string): string => {
    switch (type) {
      case 'approval':
        return t('intervene.typeApproval', { defaultValue: 'Approval' })
      case 'choice':
        return t('intervene.typeChoice', { defaultValue: 'Choice' })
      case 'text':
        return t('intervene.typeText', { defaultValue: 'Text Input' })
      default:
        return type
    }
  }

  const formatPendingSince = (ts: string): string => {
    try {
      return new Date(ts).toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      } as Intl.DateTimeFormatOptions)
    } catch {
      return ts
    }
  }

  return (
    <Box
      sx={{
        display: 'flex',
        alignItems: 'center',
        gap: 1.5,
        p: 1.5,
        bgcolor: '#FFF8E1',
        border: 1,
        borderColor: '#FFE0B2',
        borderBottom: 2,
        borderBottomColor: '#FF9800',
        borderRadius: 0.5,
        mb: 2,
        position: 'sticky',
        top: 0,
        zIndex: 40,
        animation: 'bannerIn 0.35s ease',
        '@keyframes bannerIn': {
          from: { opacity: 0, transform: 'translateY(-8px)' },
          to: { opacity: 1, transform: 'translateY(0)' },
        },
      }}
    >
      {/* Animated spinner */}
      <Box
        sx={{
          width: 20,
          height: 20,
          border: '3px solid #FFE0B2',
          borderTopColor: '#FF9800',
          borderRadius: '50%',
          animation: 'ivSpin 0.9s linear infinite',
          flexShrink: 0,
          '@keyframes ivSpin': {
            to: { transform: 'rotate(360deg)' },
          },
        }}
      />

      {/* Body */}
      <Box sx={{ flex: 1 }}>
        <Typography variant="body2" sx={{ fontSize: 13, fontWeight: 600, color: '#92400E' }}>
          {t('executions.pendingBanner.title', { defaultValue: 'Intervention Required — Delegated sub-agent needs input' })}
        </Typography>
        <Typography variant="caption" sx={{ fontSize: 11, color: '#A16207', display: 'block' }}>
          {t('executions.pendingBanner.subtitle', {
            defaultValue: '{{type}} requested by {{agent}} · pending since {{time}}',
            type: typeLabel(interventionType),
            agent: subAgentName,
            time: formatPendingSince(pendingSince),
          })}
        </Typography>
      </Box>

      {/* Respond Now button */}
      <Button
        onClick={onRespond}
        variant="contained"
        sx={{
          py: 0.6,
          px: 2,
          bgcolor: '#FF9800',
          color: '#fff',
          fontWeight: 600,
          fontSize: 12,
          textTransform: 'none',
          '&:hover': { bgcolor: '#F57C00', opacity: 0.85 },
          borderRadius: 0.5,
          flexShrink: 0,
        }}
      >
        {t('executions.pendingBanner.respondNow', { defaultValue: 'Respond Now ↓' })}
      </Button>
    </Box>
  )
}
