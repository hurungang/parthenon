import { useMemo, useState, useEffect } from 'react'
import { usePagination } from '../../hooks/usePagination'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import {
  Box,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  Typography,
  Chip,
  Collapse,
  IconButton,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Button,
} from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { ConversationSession, ConversationSessionDetail } from '../../types'
function SessionRow({ session }: { session: ConversationSession }) {
  const [open, setOpen] = useState(false)

  const { data: detail } = useQuery<ConversationSessionDetail>({
    queryKey: ['conversations', session.id],
    queryFn: async () => {
      const { data } = await apiClient.get<ConversationSessionDetail>(`/conversations/${session.id}`)
      return data
    },
    enabled: open,
  })

  return (
    <>
      <TableRow>
        <TableCell>
          <IconButton size="small" onClick={() => setOpen(!open)}>
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell><code>{session.id.substring(0, 8)}…</code></TableCell>
        <TableCell>{session.channel}</TableCell>
        <TableCell>{session.turn_count}</TableCell>
        <TableCell>
          <Chip
            label={session.status}
            color={session.status === 'active' ? 'success' : 'default'}
            size="small"
          />
        </TableCell>
        <TableCell>{new Date(session.created_at).toLocaleString()}</TableCell>
      </TableRow>
      <TableRow>
        <TableCell style={{ paddingBottom: 0, paddingTop: 0 }} colSpan={6}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <Box sx={{ margin: 2 }}>
              {detail?.turns.map((turn) => (
                <Box key={turn.id} sx={{ mb: 1, p: 1, bgcolor: 'grey.50', borderRadius: 1 }}>
                  <Typography variant="caption" color="text.secondary">
                    [{turn.role}] {new Date(turn.created_at).toLocaleTimeString()}
                  </Typography>
                  <Typography variant="body2">{turn.content}</Typography>
                  {turn.tool_calls.map((tc) => (
                    <Box key={tc.id} sx={{ mt: 0.5, pl: 2, borderLeft: (theme) => `2px solid ${theme.palette.primary.main}` }}>
                      <Typography variant="caption"><strong>Tool:</strong> {tc.tool_name}</Typography>
                    </Box>
                  ))}
                </Box>
              ))}
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  )
}

/**
 * Conversation history page — session list with turn viewer.
 * Supports filtering by agent type via URL query param: ?agentTypeId=xxx
 */
export function ConversationHistoryPage() {
  const { t } = useTranslation()
  const [searchParams, setSearchParams] = useSearchParams()
  const agentTypeIdParam = searchParams.get('agentTypeId')
  const [selectedAgentTypeId, setSelectedAgentTypeId] = useState<string>(agentTypeIdParam ?? '')
  const pag = usePagination()

  // Sync state with URL parameter changes
  useEffect(() => {
    setSelectedAgentTypeId(agentTypeIdParam ?? '')
  }, [agentTypeIdParam])

  const { data: sessions, isLoading, error } = useQuery<ConversationSession[]>({
    queryKey: ['conversations', { page: pag.page, rowsPerPage: pag.rowsPerPage }],
    queryFn: async () => {
      const { data } = await apiClient.get<ConversationSession[]>('/conversations', {
        params: { limit: pag.limit, offset: pag.offset },
      })
      return data
    },
  })

  const { data: agentTypes } = useAgentTypes()

  // Filter and sort sessions: exclude active, filter by agent type, sort by time
  const filteredSessions = useMemo(() => {
    if (!sessions) return []
    // Exclude active sessions (only show closed and archived)
    let filtered = sessions.filter(s => s.status !== 'active')
    // Filter by agent type if selected
    if (selectedAgentTypeId) {
      filtered = filtered.filter(s => s.agent_type_id === selectedAgentTypeId)
    }
    // Sort by created_at descending (newest first)
    return filtered.sort((a, b) => 
      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }, [sessions, selectedAgentTypeId])

  const handleAgentTypeChange = (agentTypeId: string) => {
    setSelectedAgentTypeId(agentTypeId)
    if (agentTypeId) {
      setSearchParams({ agentTypeId })
    } else {
      setSearchParams({})
    }
  }

  const handleClearFilter = () => {
    setSelectedAgentTypeId('')
    setSearchParams({})
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>{t('conversations.title')}</Typography>

      {/* Filter by Agent Type */}
      <Box display="flex" gap={2} mb={3}>
        <FormControl sx={{ minWidth: 300 }} size="small">
          <InputLabel>{t('conversations.filterByAgent')}</InputLabel>
          <Select
            value={selectedAgentTypeId}
            label={t('conversations.filterByAgent')}
            onChange={(e) => handleAgentTypeChange(e.target.value)}
          >
            <MenuItem value="">{t('agents.sessions.allTypes')}</MenuItem>
            {agentTypes?.map(at => (
              <MenuItem key={at.id} value={at.id}>{at.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        {selectedAgentTypeId && (
          <Button onClick={handleClearFilter}>{t('agents.sessions.clearFilters')}</Button>
        )}
      </Box>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <CircularProgress />
      ) : (
        <Box>
          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell />
                  <TableCell>ID</TableCell>
                  <TableCell>{t('conversations.channel')}</TableCell>
                  <TableCell>{t('conversations.turns')}</TableCell>
                  <TableCell>{t('app.status')}</TableCell>
                  <TableCell>{t('app.createdAt')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(filteredSessions ?? []).map((s) => (
                  <SessionRow key={s.id} session={s} />
                ))}
                {(filteredSessions ?? []).length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} align="center">{t('app.noData')}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
          <TablePagination
            component="div"
            count={-1}
            page={pag.page}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        </Box>
      )}
    </Box>
  )
}
