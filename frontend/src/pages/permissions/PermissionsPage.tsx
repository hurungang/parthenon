import { useState, type SyntheticEvent } from 'react'
import { Box, Tab, Tabs, Typography } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { TagsPage } from './TagsPage'
import { RolesPage } from './RolesPage'
import { GroupsPage } from './GroupsPage'
import { UsersPage } from './UsersPage'
import { AccessRequestsPage } from './AccessRequestsPage'

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
 * Permission Management layout with tab navigation for the five sub-pages.
 * All routes under /permissions are gated by admin role check in AppRouter.
 */
export function PermissionsPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState(0)

  const handleTabChange = (_: SyntheticEvent, newValue: number) => {
    setTab(newValue)
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} gutterBottom>
        {t('permissions.title')}
      </Typography>
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={tab} onChange={handleTabChange} aria-label={t('permissions.title')}>
          <Tab label={t('permissions.tabs.tags')} id="perm-tab-0" />
          <Tab label={t('permissions.tabs.roles')} id="perm-tab-1" />
          <Tab label={t('permissions.tabs.groups')} id="perm-tab-2" />
          <Tab label={t('permissions.tabs.users')} id="perm-tab-3" />
          <Tab label={t('permissions.tabs.accessRequests')} id="perm-tab-4" />
        </Tabs>
      </Box>
      <TabPanel value={tab} index={0}><TagsPage /></TabPanel>
      <TabPanel value={tab} index={1}><RolesPage /></TabPanel>
      <TabPanel value={tab} index={2}><GroupsPage /></TabPanel>
      <TabPanel value={tab} index={3}><UsersPage /></TabPanel>
      <TabPanel value={tab} index={4}><AccessRequestsPage /></TabPanel>
    </Box>
  )
}
