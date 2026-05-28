import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import ReplayIcon from '@mui/icons-material/Replay'
import StopIcon from '@mui/icons-material/Stop'
import ArchiveIcon from '@mui/icons-material/Archive'
import {
  useArchiveConversationSession,
  useConversationSessions,
  useEndConversationSession,
} from '../../hooks/useConversationSessions'
import { useAgentType } from '../../hooks/useAgentTypes'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { ConversationDialog } from './ConversationDialog'
import type { ConversationStatus } from '../../types'

interface ConversationSessionsTabProps {
  agentTypeId: string
  onClose?: () => void
}

type ConfirmAction = { type: 'end' | 'archive'; sessionId: string } | null

function statusColor(
  status: ConversationStatus,
): 'default' | 'success' | 'error' | 'warning' {
  if (status === 'active') return 'success'
  if (status === 'error') return 'error'
  if (status === 'archived') return 'warning'
  return 'default'
}

/**
 * Lists conversation sessions for an agent type with Resume, End, and Archive actions.
 * Follows the Dialog Error Handling Standard for all confirmation dialogs.
 */
export function ConversationSessionsTab({ agentTypeId, onClose }: ConversationSessionsTabProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [confirmAction, setConfirmAction] = useState<ConfirmAction>(null)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [conversationDialogOpen, setConversationDialogOpen] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  const { data: allSessions, isLoading, error } = useConversationSessions(agentTypeId)
  const { data: agentType } = useAgentType(agentTypeId)
  const endMutation = useEndConversationSession(agentTypeId)
  const archiveMutation = useArchiveConversationSession(agentTypeId)

  // Filter, sort, and limit sessions
  const sessions = useMemo(() => {
    if (!allSessions) return []
    // Exclude archived sessions
    const filtered = allSessions.filter(s => s.status !== 'archived')
    // Sort: active first, then closed, by updated_at desc
    const sorted = filtered.sort((a, b) => {
      if (a.status === 'active' && b.status !== 'active') return -1
      if (a.status !== 'active' && b.status === 'active') return 1
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    })
    // Limit to top 10
    return sorted.slice(0, 10)
  }, [allSessions])

  const handleViewMore = () => {
    // Close parent dialog before navigating
    if (onClose) onClose()
    navigate(`/conversations?agentTypeId=${agentTypeId}`)
  }

  const handleResume = (sessionId: string) => {
    setSelectedSessionId(sessionId)
    setConversationDialogOpen(true)
  }

  const handleCloseConversationDialog = () => {
    setConversationDialogOpen(false)
    setSelectedSessionId(null)
  }

  const handleConfirm = async () => {
    if (!confirmAction) return
    try {
      setDialogError(null)
      if (confirmAction.type === 'end') {
        await endMutation.mutateAsync(confirmAction.sessionId)
      } else {
        await archiveMutation.mutateAsync(confirmAction.sessionId)
      }
      setConfirmAction(null)
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleCloseDialog = () => {
    setConfirmAction(null)
    setDialogError(null)
  }

  return (
    <Box>
      <Box display="flex" alignItems="center" mb={2}>
        <Typography variant="subtitle1" fontWeight={600}>
          {t('conversations.sessions.title')}
        </Typography>
      </Box>

      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      {isLoading ? (
        <Box display="flex" justifyContent="center" pt={4}>
          <CircularProgress />
        </Box>
      ) : !sessions || sessions.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: 'center' }}>
          <Typography color="text.secondary">{t('conversations.sessions.empty')}</Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>{t('conversations.sessions.sessionTitle')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('app.updatedAt')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sessions.map((session) => (
                <TableRow key={session.id} hover>
                  <TableCell>
                    <Typography variant="body2">
                      {session.title ?? (
                        <Typography component="em" color="text.secondary">
                          {t('conversations.sessions.untitled')}
                        </Typography>
                      )}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    <Chip
                      label={t(`conversations.sessions.status.${session.status}`)}
                      color={statusColor(session.status)}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography variant="body2">
                      {new Date(session.updated_at).toLocaleString()}
                    </Typography>
                  </TableCell>
                  <TableCell align="right">
                    <Box display="flex" gap={0.5} justifyContent="flex-end">
                      {session.status === 'active' && (
                        <Tooltip title={t('conversations.sessions.resume')}>
                          <IconButton
                            size="small"
                            color="primary"
                            aria-label={t('conversations.sessions.resume')}
                            onClick={() => handleResume(session.id)}
                          >
                            <ReplayIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {session.status === 'active' && (
                        <Tooltip title={t('conversations.sessions.end')}>
                          <IconButton
                            size="small"
                            aria-label={t('conversations.sessions.end')}
                            onClick={() => setConfirmAction({ type: 'end', sessionId: session.id })}
                          >
                            <StopIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                      {session.status !== 'archived' && (
                        <Tooltip title={t('conversations.sessions.archive')}>
                          <IconButton
                            size="small"
                            aria-label={t('conversations.sessions.archive')}
                            onClick={() =>
                              setConfirmAction({ type: 'archive', sessionId: session.id })
                            }
                          >
                            <ArchiveIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {allSessions && allSessions.length > 10 && (
            <Box display="flex" justifyContent="center" mt={2}>
              <Button onClick={handleViewMore}>
                {t('conversations.sessions.viewMore')}
              </Button>
            </Box>
          )}
        </TableContainer>
      )}

      {/* Confirmation dialog for End / Archive actions */}
      <Dialog
        open={confirmAction !== null}
        onClose={handleCloseDialog}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>
          {confirmAction?.type === 'end'
            ? t('conversations.sessions.endConfirmTitle')
            : t('conversations.sessions.archiveConfirmTitle')}
        </DialogTitle>
        <DialogContent>
          {dialogError != null && (
            <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
          )}
          <Typography variant="body2">
            {confirmAction?.type === 'end'
              ? t('conversations.sessions.endConfirmBody')
              : t('conversations.sessions.archiveConfirmBody')}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseDialog}>{t('app.cancel')}</Button>
          <Button
            variant="contained"
            color={confirmAction?.type === 'end' ? 'error' : 'warning'}
            onClick={() => void handleConfirm()}
            disabled={endMutation.isPending || archiveMutation.isPending}
          >
            {t('app.confirm')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Conversation Dialog */}
      {conversationDialogOpen && (
        <ConversationDialog
          open={true}
          sessionId={selectedSessionId}
          agentTypeId={agentTypeId}
          agentTypeName={agentType?.name ?? 'Agent'}
          onClose={handleCloseConversationDialog}
        />
      )}
    </Box>
  )
}
