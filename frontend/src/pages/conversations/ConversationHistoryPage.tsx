import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  CircularProgress,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Chip,
  Collapse,
  IconButton,
} from '@mui/material'
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown'
import KeyboardArrowUpIcon from '@mui/icons-material/KeyboardArrowUp'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
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
 */
export function ConversationHistoryPage() {
  const { t } = useTranslation()

  const { data: sessions, isLoading } = useQuery<ConversationSession[]>({
    queryKey: ['conversations'],
    queryFn: async () => {
      const { data } = await apiClient.get<ConversationSession[]>('/conversations')
      return data
    },
  })

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={3}>{t('conversations.title')}</Typography>

      {isLoading ? (
        <CircularProgress />
      ) : (
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
              {(sessions ?? []).map((s) => (
                <SessionRow key={s.id} session={s} />
              ))}
              {(sessions ?? []).length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} align="center">{t('app.noData')}</TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
