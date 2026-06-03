import { useState, type SyntheticEvent } from 'react'
import { Box, Tab, Tabs, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { ChannelListPage } from './ChannelListPage'
import { RecipientGroupListPage } from './RecipientGroupListPage'
import { NotificationLogPage } from './NotificationLogPage'

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

export function NotificationConfigPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)

  const handleTabChange = (_: SyntheticEvent, newValue: number) => {
    setTab(newValue)
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('notifications.title')}
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tab} onChange={handleTabChange} aria-label={t('notifications.title')}>
          <Tab label={t('notifications.channels.title')} id="notif-tab-0" />
          <Tab label={t('notifications.groups.title')} id="notif-tab-1" />
          <Tab label={t('notifications.logs.title')} id="notif-tab-2" />
        </Tabs>
      </Box>
      <TabPanel value={tab} index={0}><ChannelListPage /></TabPanel>
      <TabPanel value={tab} index={1}><RecipientGroupListPage /></TabPanel>
      <TabPanel value={tab} index={2}><NotificationLogPage /></TabPanel>
    </Box>
  )
}
