import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  List,
  ListItemButton,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import SearchIcon from '@mui/icons-material/Search'
import PermissionDeniedAlert from '../../permissions/PermissionDeniedAlert'
import type { AgentType } from '../../../types'

interface AgentListSidebarProps {
  agents: AgentType[]
  loading: boolean
  error: unknown
  selectedId: string | null
  onSelect: (agentTypeId: string) => void
  onCreate: () => void
}

// Hard cap for per-item descriptions: substring in JS so long text can never
// stretch the sidebar items or the layout.
const SIDEBAR_DESCRIPTION_MAX_LENGTH = 60

function truncateSidebarDescription(value: string): string {
  if (value.length <= SIDEBAR_DESCRIPTION_MAX_LENGTH) return value
  return `${value.slice(0, SIDEBAR_DESCRIPTION_MAX_LENGTH).trimEnd()}…`
}

/**
 * Agent list sidebar of the Agent Management Panel: client-side search over the
 * fetched agent types, selection highlight, and loading / empty / permission
 * error states per the platform pattern (graceful 403 degradation).
 */
export function AgentListSidebar({
  agents,
  loading,
  error,
  selectedId,
  onSelect,
  onCreate,
}: AgentListSidebarProps) {
  const { t } = useTranslation()
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return agents
    return agents.filter(
      (agent) =>
        agent.name.toLowerCase().includes(query) ||
        (agent.description ?? '').toLowerCase().includes(query),
    )
  }, [agents, search])

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        gap: 1,
        height: '100%',
        minHeight: 0,
        // Contain every child to the card width: flex children default to
        // min-width:auto, so the noWrap list rows' min-content (full
        // un-truncated text width) would otherwise size the rows wider than
        // the column and stretch the search field / create button with it.
        width: '100%',
        minWidth: 0,
        maxWidth: '100%',
        overflow: 'hidden',
        '& > *': {
          minWidth: 0,
          maxWidth: '100%',
          overflow: 'hidden',
        },
      }}
    >
      <Box display="flex" alignItems="center" justifyContent="space-between">
        <Typography variant="subtitle1" fontWeight={600}>
          {t('agents.panel.agentList')}
        </Typography>
        {agents.length > 0 && (
          <Typography variant="caption" color="text.secondary">
            {t('agents.panel.agentCount', { count: agents.length })}
          </Typography>
        )}
      </Box>

      <TextField
        size="small"
        placeholder={t('agents.panel.searchPlaceholder')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        InputProps={{
          startAdornment: (
            <SearchIcon fontSize="small" sx={{ mr: 1, color: 'text.secondary' }} />
          ),
        }}
        aria-label={t('agents.panel.searchPlaceholder')}
      />

      <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
        {loading && (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress size={28} />
          </Box>
        )}
        {!loading && error != null && (
          <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
        )}
        {!loading && !error && filtered.length === 0 && (
          <Typography variant="body2" color="text.secondary" py={2} textAlign="center">
            {search.trim() ? t('agents.panel.noSearchResults') : t('agents.panel.noAgents')}
          </Typography>
        )}
        {!loading && !error && filtered.length > 0 && (
          <List dense disablePadding>
            {filtered.map((agent) => (
              <ListItemButton
                key={agent.id}
                selected={agent.id === selectedId}
                onClick={() => onSelect(agent.id)}
                sx={{ borderRadius: 1, mb: 0.5, minWidth: 0, overflow: 'hidden' }}
              >
                <ListItemText
                  primary={agent.name}
                  secondary={agent.description ? truncateSidebarDescription(agent.description) : undefined}
                  primaryTypographyProps={{ noWrap: true }}
                  secondaryTypographyProps={{ noWrap: true }}
                />
              </ListItemButton>
            ))}
          </List>
        )}
      </Box>

      <Button variant="contained" startIcon={<AddIcon />} onClick={onCreate}>
        {t('agents.panel.createAgent')}
      </Button>
    </Box>
  )
}
