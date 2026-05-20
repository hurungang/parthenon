import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  TextField,
  Typography,
  IconButton,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PersonIcon from '@mui/icons-material/Person'
import ExitToAppIcon from '@mui/icons-material/ExitToApp'
import StopCircleIcon from '@mui/icons-material/StopCircle'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { useChatSession, type ChatMessage } from '../../hooks/useChatSession'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import { useEndConversationSession } from '../../hooks/useConversationSessions'
import type { ConversationSession, ConversationSessionDetail } from '../../types'

/**
 * Real-time user-to-agent chat interface backed by WebSocket.
 * Supports starting a new conversation session or resuming an existing one.
 */
export function ChatPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  // sessionId here is the conversation session ID from the URL
  const { agentTypeId, sessionId: urlSessionId } = useParams<{
    agentTypeId: string
    sessionId: string
  }>()
  const { data: agentTypes } = useAgentTypes()
  const [wsSessionId, setWsSessionId] = useState<string | null>(null)
  const [convSessionId, setConvSessionId] = useState<string | null>(null)
  const [resumedMessages, setResumedMessages] = useState<ChatMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [isStarting, setIsStarting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [endError, setEndError] = useState<unknown>(null)
  const [endConfirmOpen, setEndConfirmOpen] = useState(false)

  const endSession = useEndConversationSession(agentTypeId ?? '')
  const queryClient = useQueryClient()

  const handleExit = () => {
    navigate('/agents', { state: { openDialogFor: agentTypeId } })
  }

  const handleEndSession = async () => {
    if (!convSessionId) return
    setEndError(null)
    try {
      await endSession.mutateAsync(convSessionId)
      setEndConfirmOpen(false)
      navigate('/agents', { state: { openDialogFor: agentTypeId } })
    } catch (err) {
      setEndError(err)
    }
  }

  const { messages: wsMessages, connected, pendingQuestion, sessionTitle, sendMessage } =
    useChatSession(wsSessionId, convSessionId)

  // Combine resumed history with live WebSocket messages
  const messages = [...resumedMessages, ...wsMessages]

  // Auto-resume session if sessionId is in URL
  // (User navigated here from Resume button or direct link)
  useEffect(() => {
    if (urlSessionId && !convSessionId) {
      void handleResumeSession(urlSessionId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlSessionId])

  // Refresh the sessions list immediately when the auto-generated title arrives
  useEffect(() => {
    if (sessionTitle && agentTypeId) {
      void queryClient.invalidateQueries({ queryKey: ['conversations', agentTypeId] })
    }
  }, [sessionTitle, agentTypeId, queryClient])

  const handleResumeSession = async (sessionId: string) => {
    setIsStarting(true)
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
      // Use conv session id as ws handle (since there's no separate AgentJob yet)
      setWsSessionId(data.id)
    } catch (err) {
      setError(err)
    } finally {
      setIsStarting(false)
    }
  }

  const handleStartSession = async () => {
    if (!agentTypeId) return
    setIsStarting(true)
    setError(null)
    try {
      const { data } = await apiClient.post<ConversationSession>('/conversations', {
        agent_type_id: agentTypeId,
      })
      setConvSessionId(data.id)
      setWsSessionId(data.id)
    } catch (err) {
      setError(err)
    } finally {
      setIsStarting(false)
    }
  }

  const handleSend = () => {
    if (!inputText.trim()) return
    sendMessage(inputText.trim())
    setInputText('')
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const agentType = agentTypes?.find((at) => at.id === agentTypeId)
  // Live title from WebSocket auto-naming, or fallback to agent name
  const displayTitle = sessionTitle ?? agentType?.name ?? t('nav.agents')

  return (
    <Box display="flex" flexDirection="column" height="100%">
      {/* Header */}
      <Box display="flex" alignItems="center" gap={1} mb={2}>
        <SmartToyIcon color="primary" />
        <Typography variant="h5" fontWeight={700}>
          {displayTitle}
        </Typography>
        {convSessionId && (
          <Chip
            label={connected ? t('conversations.sessions.connected') : t('conversations.sessions.disconnected')}
            color={connected ? 'success' : 'error'}
            size="small"
          />
        )}
        {convSessionId && (
          <Box display="flex" gap={1} sx={{ ml: 'auto' }}>
            <Button
              variant="outlined"
              size="small"
              startIcon={<ExitToAppIcon />}
              onClick={handleExit}
            >
              {t('conversations.sessions.exit')}
            </Button>
            <Button
              variant="outlined"
              color="error"
              size="small"
              startIcon={<StopCircleIcon />}
              onClick={() => setEndConfirmOpen(true)}
              disabled={endSession.isPending}
            >
              {t('conversations.sessions.end')}
            </Button>
          </Box>
        )}
      </Box>

      {error ? <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} /> : null}
      {endError ? <PermissionDeniedAlert error={endError} fallbackMessage={t('app.error')} /> : null}

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

      {!convSessionId ? (
        <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
          <Box textAlign="center">
            <SmartToyIcon sx={{ fontSize: 64, color: 'primary.main', mb: 2 }} />
            <Typography variant="h6" mb={2}>
              {agentType
                ? t('conversations.sessions.startPrompt', { name: agentType.name })
                : t('conversations.sessions.selectAgent')}
            </Typography>
            {agentType && (
              <button
                onClick={() => void handleStartSession()}
                disabled={isStarting}
                style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
              >
                {isStarting ? t('app.loading') : t('conversations.sessions.startNew')}
              </button>
            )}
          </Box>
        </Box>
      ) : (
        <>
          {/* Messages list */}
          <Paper
            variant="outlined"
            sx={{ flex: 1, overflow: 'auto', p: 2, mb: 2, bgcolor: 'grey.50' }}
          >
            {messages.map((msg: ChatMessage) => (
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
                  {msg.role === 'user' ? (
                    <PersonIcon fontSize="small" />
                  ) : (
                    <SmartToyIcon fontSize="small" />
                  )}
                </Avatar>
                <Paper
                  elevation={1}
                  sx={{
                    p: 1.5,
                    maxWidth: '70%',
                    bgcolor: msg.role === 'user' ? 'primary.light' : 'background.paper',
                    color: msg.role === 'user' ? 'primary.contrastText' : 'text.primary',
                  }}
                >
                  <Typography variant="body2">{msg.content}</Typography>
                  <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
                    {new Date(msg.timestamp).toLocaleTimeString()}
                  </Typography>
                </Paper>
              </Box>
            ))}
            {messages.length === 0 && (
              <Typography variant="body2" color="text.secondary" textAlign="center" mt={4}>
                {t('conversations.sessions.chatEmpty')}
              </Typography>
            )}
          </Paper>

          {/* Pending question indicator */}
          {pendingQuestion && (
            <Alert severity="info" sx={{ mb: 1 }}>
              {t('conversations.session')}: {pendingQuestion}
            </Alert>
          )}

          {/* Input area */}
          <Box display="flex" gap={1}>
            <TextField
              fullWidth
              multiline
              maxRows={4}
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={t('conversations.sessions.chatPlaceholder')}
              size="small"
              disabled={!connected}
            />
            <IconButton
              color="primary"
              onClick={handleSend}
              disabled={!connected || !inputText.trim()}
            >
              <SendIcon />
            </IconButton>
          </Box>
        </>
      )}
    </Box>
  )
}
