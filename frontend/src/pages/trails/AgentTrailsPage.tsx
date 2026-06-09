import { useState, type SyntheticEvent } from 'react'
import { Box, Tab, Tabs, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { ConversationHistoryPage } from '../conversations/ConversationHistoryPage'
import { AgentInstanceDashboardPage } from '../agents/AgentInstanceDashboardPage'
import { ResultRepositoryPage } from '../results/ResultRepositoryPage'

interface TabPanelProps {
  children: React.ReactNode
  index: number
  value: number
}

function TabPanel({ children, value, index }: TabPanelProps) {
  return (
    <Box role="tabpanel" hidden={value !== index} sx={{ pt: 2 }}>
      {value === index && children}
    </Box>
  )
}

/**
 * Agent Trails module — groups Conversation History, Agent Executions, and
 * Result Repository as tabs within a single page.
 */
export function AgentTrailsPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)

  const handleTabChange = (_: SyntheticEvent, newValue: number) => {
    setTab(newValue)
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('nav.agentTrails')}
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tab} onChange={handleTabChange} aria-label={t('nav.agentTrails')}>
          <Tab label={t('nav.agentExecutions')} id="trails-tab-0" />
          <Tab label={t('nav.results')} id="trails-tab-1" />
          <Tab label={t('nav.agentLogs')} id="trails-tab-2" />
        </Tabs>
      </Box>
      <TabPanel value={tab} index={0}><AgentInstanceDashboardPage /></TabPanel>
      <TabPanel value={tab} index={1}><ResultRepositoryPage /></TabPanel>
      <TabPanel value={tab} index={2}><ConversationHistoryPage /></TabPanel>
    </Box>
  )
}
