import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Avatar,
  Box,
  Chip,
  Paper,
  TextField,
  Typography,
  IconButton,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import PersonIcon from '@mui/icons-material/Person'
import apiClient from '../../api/apiClient'
import { useChatSession, type ChatMessage } from '../../hooks/useChatSession'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import type { GatewayInitResponse } from '../../types'

/**
 * Real-time user-to-agent chat interface backed by WebSocket.
 */
export function ChatPage() {
  const { t } = useTranslation()
  const { agentTypeId } = useParams<{ agentTypeId: string }>()
  const { data: agentTypes } = useAgentTypes()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [inputText, setInputText] = useState('')
  const [isStarting, setIsStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { messages, connected, pendingQuestion, sendMessage } = useChatSession(sessionId)

  const handleStartSession = async () => {
    if (!agentTypeId) return
    setIsStarting(true)
    setError(null)
    try {
      const { data } = await apiClient.post<GatewayInitResponse>(
        `/gateway/${agentTypeId}/init`,
        {},
      )
      setSessionId(data.instance_id)
    } catch {
      setError(t('app.error'))
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

  return (
    <Box display="flex" flexDirection="column" height="100%">
      {/* Header */}
      <Box display="flex" alignItems="center" gap={1} mb={2}>
        <SmartToyIcon color="primary" />
        <Typography variant="h5" fontWeight={700}>
          {agentType?.name ?? t('nav.agents')}
        </Typography>
        {sessionId && (
          <Chip
            label={connected ? 'Connected' : 'Disconnected'}
            color={connected ? 'success' : 'error'}
            size="small"
          />
        )}
      </Box>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      {!sessionId ? (
        <Box display="flex" justifyContent="center" alignItems="center" flex={1}>
          <Box textAlign="center">
            <SmartToyIcon sx={{ fontSize: 64, color: 'primary.main', mb: 2 }} />
            <Typography variant="h6" mb={2}>
              {agentType ? `Start a session with ${agentType.name}` : 'Select an agent type'}
            </Typography>
            {agentType && (
              <button
                onClick={handleStartSession}
                disabled={isStarting}
                style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
              >
                {isStarting ? t('app.loading') : 'Start Chat'}
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
                <Avatar sx={{ width: 32, height: 32, bgcolor: msg.role === 'user' ? 'primary.main' : 'secondary.main' }}>
                  {msg.role === 'user' ? <PersonIcon fontSize="small" /> : <SmartToyIcon fontSize="small" />}
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
                Send a message to begin
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
              placeholder="Type a message..."
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
