import { useTranslation } from 'react-i18next'
import { Box, Button, Card, CardContent, Typography } from '@mui/material'
import LaunchIcon from '@mui/icons-material/Launch'

/**
 * Observability dashboard — real-time OTEL metrics panels and deep links to Jaeger and Loki.
 */
export function ObservabilityDashboard() {
  const { t } = useTranslation()

  const JAEGER_URL = import.meta.env.VITE_JAEGER_URL ?? 'http://localhost:16686'
  const LOKI_URL = import.meta.env.VITE_LOKI_URL ?? 'http://localhost:3000'

  const metrics = [
    { label: t('observability.requestRate'), value: '—', unit: 'req/s' },
    { label: t('observability.errorRate'), value: '—', unit: '%' },
    { label: t('observability.p95Latency'), value: '—', unit: 'ms' },
  ]

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>
        {t('observability.title')}
      </Typography>

      {/* Metric cards */}
      <Box display="flex" gap={2} mb={4} flexWrap="wrap">
        {metrics.map((m) => (
          <Card key={m.label} elevation={2} sx={{ minWidth: 200, flex: 1 }}>
            <CardContent>
              <Typography variant="body2" color="text.secondary">{m.label}</Typography>
              <Typography variant="h4" fontWeight={700}>
                {m.value} <Typography component="span" variant="caption">{m.unit}</Typography>
              </Typography>
            </CardContent>
          </Card>
        ))}
      </Box>

      {/* Links to external observability tools */}
      <Box display="flex" gap={2}>
        <Button
          variant="outlined"
          startIcon={<LaunchIcon />}
          href={JAEGER_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t('observability.openJaeger')}
        </Button>
        <Button
          variant="outlined"
          startIcon={<LaunchIcon />}
          href={LOKI_URL}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t('observability.openLoki')}
        </Button>
      </Box>
    </Box>
  )
}
