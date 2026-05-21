import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  Avatar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PersonIcon from '@mui/icons-material/Person'
import CloseIcon from '@mui/icons-material/Close'
import StopCircleIcon from '@mui/icons-material/StopCircle'
import FullscreenIcon from '@mui/icons-material/Fullscreen'
import FullscreenExitIcon from '@mui/icons-material/FullscreenExit'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import { useChatSession, type ChatMessage } from '../../hooks/useChatSession'
import { useEndConversationSession } from '../../hooks/useConversationSessions'
import type { ConversationSessionDetail } from '../../types'

interface ConversationDialogProps {
  open: boolean
  sessionId: string | null
  agentTypeId: string
  agentTypeName: string
  onClose: () => void
}

/**
 * Full-screen capable conversation dialog for real-time chat with agents.
 * Handles session resume, WebSocket connection, and session end.
 */
export function ConversationDialog({
  open,
  sessionId,
  agentTypeId,
  agentTypeName,
  onClose,
}: ConversationDialogProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [convSessionId, setConvSessionId] = useState<string | null>(null)
  const [wsSessionId, setWsSessionId] = useState<string | null>(null)
  const [resumedMessages, setResumedMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [isResuming, setIsResuming] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [endError, setEndError] = useState<unknown>(null)
  const [endConfirmOpen, setEndConfirmOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState(false)

  const endSession = useEndConversationSession(agentTypeId)

  const { messages: wsMessages, connected, pendingQuestion, sessionTitle, sendMessage } =
    useChatSession(wsSessionId, convSessionId)

  // Combine resumed history with live WebSocket messages
  const messages = [...resumedMessages, ...wsMessages]

  // Resume session when dialog opens with a sessionId
  // For new chats, session is created only when user sends first message
  useEffect(() => {
    if (open && sessionId && !convSessionId) {
      void handleResumeSession(sessionId)
    }
  }, [open, sessionId])

  // Refresh the sessions list when title arrives
  useEffect(() => {
    if (sessionTitle && agentTypeId) {
      void queryClient.invalidateQueries({ queryKey: ['conversations', agentTypeId] })
    }
  }, [sessionTitle, agentTypeId, queryClient])

  // Reset state and clean up empty sessions when dialog closes
  useEffect(() => {
    if (!open) {
      // Clean up empty session (no user messages sent)
      if (convSessionId && messages.filter(m => m.role === 'user').length === 0 && !sessionId) {
        // Delete empty session only if it was newly created (not resumed)
        // Use archive endpoint since there's no delete endpoint
        void apiClient.post(`/conversations/${convSessionId}/archive`).catch(() => {
          // Ignore errors - session might already be deleted
        })
      }
      
      setConvSessionId(null)
      setWsSessionId(null)
      setResumedMessages([])
      setInputText('')
      setError(null)
      setEndError(null)
      setEndConfirmOpen(false)
      setFullscreen(false)
    }
  }, [open, convSessionId, messages, sessionId])

  const handleResumeSession = async (sessionId: string) => {
    setIsResuming(true)
    setError(null)
    try {
      const { data } = await apiClient.post<ConversationSessionDetail>(
        `/conversations/${sessionId}/resume`,
      )
      setConvSessionId(data.id)
      // Convert history turns to ChatMessages for display
      const history: ChatMessage[] = (data.turns ?? []).map((turn) => ({
        id: turn.id,
        role: turn.role === 'agent' ? 'agent' : turn.role === 'user' ? 'user' : 'system',
        content: turn.content,
        timestamp: turn.created_at,
      }))
      setResumedMessages(history)
      // Use conv session id as ws handle
      setWsSessionId(data.id)
    } catch (err) {
      setError(err)
    } finally {
      setIsResuming(false)
    }
  }
  const handleStartSession = async (): Promise<string | null> => {
    setIsResuming(true)
    setError(null)
    try {
      const { data } = await apiClient.post('/conversations', {
        agent_type_id: agentTypeId,
      })
      setConvSessionId(data.id)
      setWsSessionId(data.id)
      return data.id
    } catch (err) {
      setError(err)
      return null
    } finally {
      setIsResuming(false)
    }
  }
  const handleEndSession = async () => {
    if (!convSessionId) return
    setEndError(null)
    try {
      await endSession.mutateAsync(convSessionId)
      setEndConfirmOpen(false)
      onClose() // Close dialog after ending session
    } catch (err) {
      setEndError(err)
    }
  }

  const handleSend = async () => {
    if (!inputText.trim()) return
    const messageToSend = inputText.trim()
    if (isResuming) return

    // If no session exists yet, create it before sending first message
    if (!convSessionId) {
      const startedSessionId = await handleStartSession()
      if (!startedSessionId) {
        return
      }
    }

    // sendMessage queues when socket is not OPEN yet, then flushes on onopen.
    const wasQueuedOrSent = sendMessage(messageToSend)
    if (wasQueuedOrSent) {
      setInputText('')
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  const displayTitle = sessionTitle ?? agentTypeName

  return (
    <>
      <Dialog
        open={open}
        onClose={onClose}
        maxWidth={fullscreen ? false : 'lg'}
        fullWidth
        fullScreen={fullscreen}
        PaperProps={{
          sx: {
            height: fullscreen ? '100%' : '80vh',
          },
        }}
      >
        <DialogTitle>
          <Box display="flex" alignItems="center" gap={1}>
            <SmartToyIcon color="primary" />
            <Typography variant="h6" component="span" fontWeight={600}>
              {displayTitle}
            </Typography>
            {convSessionId && (
              <Chip
                label={connected ? t('conversations.sessions.connected') : t('conversations.sessions.disconnected')}
                color={connected ? 'success' : 'error'}
                size="small"
              />
            )}
            <Box sx={{ ml: 'auto' }} display="flex" gap={1}>
              <IconButton size="small" onClick={() => setFullscreen(!fullscreen)}>
                {fullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
              </IconButton>
              <IconButton size="small" onClick={onClose}>
                <CloseIcon />
              </IconButton>
            </Box>
          </Box>
        </DialogTitle>

        <DialogContent dividers sx={{ display: 'flex', flexDirection: 'column', p: 0 }}>
          {Boolean(error) && (
            <Box p={2}>
              <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />
            </Box>
          )}

          {isResuming ? (
            <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
              <Typography>{t('app.loading')}</Typography>
            </Box>
          ) : (
            <>
              {/* Messages list */}
              <Paper
                variant="outlined"
                sx={{ flex: 1, overflow: 'auto', p: 2, m: 2, bgcolor: 'grey.50' }}
              >
                {messages.length === 0 ? (
                  <Typography color="text.secondary" align="center">
                    {t('conversations.sessions.chatEmpty')}
                  </Typography>
                ) : (
                  messages.map((msg: ChatMessage) => (
                    <Box
                      key={msg.id}
                      display="flex"
                      flexDirection={msg.role === 'user' ? 'row-reverse' : 'row'}
                      alignItems="flex-start"
                      gap={1}
                      mb={2}
                    >
                      <Avatar
                        sx={{
                          width: 32,
                          height: 32,
                          bgcolor: msg.role === 'user' ? 'primary.main' : 'secondary.main',
                        }}
                      >
                        {msg.role === 'user' ? <PersonIcon /> : <SmartToyIcon />}
                      </Avatar>
                      <Paper
                        sx={{
                          p: 1.5,
                          maxWidth: '70%',
                          bgcolor: msg.role === 'user' ? 'primary.light' : 'background.paper',
                        }}
                      >
                        <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                          {msg.content}
                        </Typography>
                      </Paper>
                    </Box>
                  ))
                )}
              </Paper>

              {/* Input box */}
              <Box p={2} pt={0}>
                <Box display="flex" gap={1}>
                  <TextField
                    fullWidth
                    multiline
                    maxRows={4}
                    value={inputText}
                    onChange={(e) => setInputText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={t('conversations.sessions.chatPlaceholder')}
                    disabled={convSessionId ? !connected || !!pendingQuestion : false}
                    size="small"
                  />
                  <Button
                    variant="contained"
                    onClick={() => void handleSend()}
                    disabled={!inputText.trim() || (convSessionId ? !connected || !!pendingQuestion : false)}
                    startIcon={<SendIcon />}
                  >
                    {t('conversations.sessions.send')}
                  </Button>
                </Box>
              </Box>
            </>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={onClose}>{t('conversations.sessions.exit')}</Button>
          {convSessionId && (
            <Button
              variant="outlined"
              color="error"
              startIcon={<StopCircleIcon />}
              onClick={() => setEndConfirmOpen(true)}
              disabled={endSession.isPending}
            >
              {t('conversations.sessions.end')}
            </Button>
          )}
        </DialogActions>
      </Dialog>

      {/* End Session confirmation dialog */}
      <Dialog
        open={endConfirmOpen}
        onClose={() => { setEndConfirmOpen(false); setEndError(null) }}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('conversations.sessions.endConfirmTitle')}</DialogTitle>
        <DialogContent dividers>
          {endError != null && (
            <PermissionDeniedAlert error={endError} fallbackMessage={t('app.error')} />
          )}
          <Typography>{t('conversations.sessions.endConfirmBody')}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEndConfirmOpen(false); setEndError(null) }}>
            {t('app.cancel')}
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => void handleEndSession()}
            disabled={endSession.isPending}
          >
            {t('conversations.sessions.end')}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
