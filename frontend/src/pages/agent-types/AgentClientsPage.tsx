import { useTranslation } from 'react-i18next'
import { Box, Typography } from '@mui/material'
import { AgentClientsPanel } from '../../components/agents/AgentClientsPanel'

/**
 * Standalone Clients page (global view across agent types).
 *
 * The primary entry point is the Clients tab on an agent type; this page is a
 * convenience view for administrators who want to see every client at once.
 */
export function AgentClientsPage() {
  const { t } = useTranslation()
  return (
    <Box sx={{ p: 3 }}>
      <Box sx={{ mb: 2 }}>
        <Typography variant="h5">{t('agentClients.title', 'Clients')}</Typography>
        <Typography variant="body2" color="text.secondary">
          {t(
            'agentClients.pageSubtitle',
            'Third-party access grants across all agent types. A client is not an agent identity.',
          )}
        </Typography>
      </Box>
      <AgentClientsPanel />
    </Box>
  )
}
