import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Divider,
  IconButton,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import SendIcon from '@mui/icons-material/Send'
import apiClient from '../../api/apiClient'
import { useChatSession } from '../../hooks/useChatSession'
import { useExecutionLogs } from '../../hooks/useExecutionLogs'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { SessionExecutionLogsDialog } from './SessionExecutionLogsDialog'
import type { AgentJob, AgentJobStatus } from '../../types'

const TERMINAL_STATUSES: AgentJobStatus[] = ['completed', 'failed']
const POLL_INTERVAL_MS = 3_000

function statusColor(status: AgentJobStatus): 'default' | 'warning' | 'info' | 'success' | 'error' {
  if (status === 'queued') return 'default'
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'error'
  return 'default'
}

/**
 * AgentJobPage — shows status and result for a single agent session.
 *
 * - Task agents: polls GET /agents/sessions/{id} every 3s until terminal status,
 *   then renders the result (structured JSON or markdown).
 * - Conversational agents: opens a WebSocket chat interface for interactive Q&A.
 */
export function AgentJobPage() {
  const { id } = useParams<{ id: string }>()
  const { t } = useTranslation()
  const navigate = useNavigate()

  const [session, setSession] = useState<AgentJob | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<unknown>(null)
  const [chatInput, setChatInput] = useState('')
  const [showLogs, setShowLogs] = useState(false)
  const [execLogExpanded, setExecLogExpanded] = useState(false)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  // Execution logs (system instruction + user prompt) via dedicated hook
  const { logs: execLogs, loading: execLogsLoading } = useExecutionLogs(id ?? null)

  // Determine if this is a conversational session based on status flow
  // (we'll fetch the agent type info implicitly from output format)
  const isConversational = session?.input_data != null &&
    typeof session.input_data === 'object' &&
    'message' in session.input_data

  // WebSocket chat — only active for conversational agents
  const { messages, sendMessage, connected } = useChatSession(
    isConversational && id ? id : null,
  )

  const fetchSession = useCallback(async () => {
    if (!id) return
    try {
      const { data } = await apiClient.get<AgentJob>(`/agents/sessions/${id}`)
      setSession(data)
      setFetchError(null)
      if (TERMINAL_STATUSES.includes(data.status)) {
        if (pollingRef.current) clearInterval(pollingRef.current)
        pollingRef.current = null
      }
    } catch (err) {
      setFetchError(err)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    void fetchSession()
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [fetchSession])

  // Start polling when session is in a non-terminal status
  useEffect(() => {
    if (!session) return
    if (TERMINAL_STATUSES.includes(session.status)) return
    if (isConversational) return // Conversational uses WebSocket

    if (!pollingRef.current) {
      pollingRef.current = setInterval(() => void fetchSession(), POLL_INTERVAL_MS)
    }
  }, [session, isConversational, fetchSession])

  // Auto-scroll chat to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSendMessage = () => {
    const msg = chatInput.trim()
    if (!msg) return
    sendMessage(msg)
    setChatInput('')
  }

  if (loading) {
    return (
      <Box display="flex" justifyContent="center" pt={8}>
        <CircularProgress />
      </Box>
    )
  }

  if (fetchError) {
    return (
      <Box>
        <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/agents')} sx={{ mb: 2 }}>
          {t('app.back')}
        </Button>
        <PermissionDeniedAlert error={fetchError} fallbackMessage={t('app.error')} />
      </Box>
    )
  }

  if (!session) return null

  const isTerminal = TERMINAL_STATUSES.includes(session.status)

  return (
    <Box>
      <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/agents')} sx={{ mb: 2 }}>
        {t('app.back')}
      </Button>

      {/* Session Metadata */}
      <Paper sx={{ p: 3, mb: 3 }}>
        <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={2}>
          <Box>
            <Typography variant="h5" fontWeight={700} mb={0.5}>
              {t('agents.sessions.sessionTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary" fontFamily="monospace">
              {session.id}
            </Typography>
          </Box>
          <Box display="flex" alignItems="center" gap={1}>
            {!isTerminal && !isConversational && (
              <CircularProgress size={16} sx={{ mr: 1 }} />
            )}
            <Chip
              label={t(`agents.sessions.status${session.status.replace(/^./, (c: string) => c.toUpperCase())}`)}
              color={statusColor(session.status)}
              size="small"
            />
            <Button variant="outlined" size="small" onClick={() => setShowLogs(true)}>
              {t('agents.sessions.viewExecutionLogs')}
            </Button>
          </Box>
        </Box>

        <Divider sx={{ mb: 2 }} />

        <Box display="grid" gridTemplateColumns="repeat(auto-fit, minmax(200px, 1fr))" gap={2}>
          <Box>
            <Typography variant="caption" color="text.secondary" display="block">
              {t('agents.sessions.createdAt')}
            </Typography>
            <Typography variant="body2">
              {new Date(session.created_at).toLocaleString()}
            </Typography>
          </Box>
          {session.started_at && (
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('agents.sessions.startedAt')}
              </Typography>
              <Typography variant="body2">
                {new Date(session.started_at).toLocaleString()}
              </Typography>
            </Box>
          )}
          {session.completed_at && (
            <Box>
              <Typography variant="caption" color="text.secondary" display="block">
                {t('agents.sessions.completedAt')}
              </Typography>
              <Typography variant="body2">
                {new Date(session.completed_at).toLocaleString()}
              </Typography>
            </Box>
          )}
        </Box>
      </Paper>

      {/* Error display */}
      {session.status === 'failed' && session.error_message && (
        <Alert severity="error" sx={{ mb: 3 }}>
          <Typography variant="subtitle2" mb={0.5}>{t('agents.sessions.errorTitle')}</Typography>
          <Typography variant="body2" fontFamily="monospace">
            {session.error_message}
          </Typography>
        </Alert>
      )}

      {/* Conversational Chat Interface */}
      {isConversational && (
        <Paper sx={{ p: 0, overflow: 'hidden' }}>
          <Box
            sx={{
              p: 1.5,
              bgcolor: 'primary.main',
              color: 'primary.contrastText',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <Typography variant="subtitle2">{t('agents.sessions.chat')}</Typography>
            <Chip
              label={connected ? t('agents.sessions.connected') : t('agents.sessions.disconnected')}
              size="small"
              color={connected ? 'success' : 'default'}
              sx={{ color: 'white', bgcolor: connected ? 'success.dark' : 'grey.600' }}
            />
          </Box>

          <Box
            sx={{
              height: 400,
              overflowY: 'auto',
              p: 2,
              display: 'flex',
              flexDirection: 'column',
              gap: 1,
            }}
          >
            {messages.length === 0 && (
              <Typography color="text.secondary" textAlign="center" mt={4}>
                {t('agents.sessions.chatEmpty')}
              </Typography>
            )}
            {messages.map((msg) => (
              <Box
                key={msg.id}
                alignSelf={msg.role === 'user' ? 'flex-end' : 'flex-start'}
                sx={{ maxWidth: '75%' }}
              >
                <Paper
                  sx={{
                    p: 1.5,
                    bgcolor: msg.role === 'user' ? 'primary.main' : 'grey.100',
                    color: msg.role === 'user' ? 'primary.contrastText' : 'text.primary',
                  }}
                >
                  <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </Typography>
                </Paper>
                <Typography variant="caption" color="text.secondary" display="block" mt={0.25}
                  textAlign={msg.role === 'user' ? 'right' : 'left'}>
                  {new Date(msg.timestamp).toLocaleTimeString()}
                </Typography>
              </Box>
            ))}
            <div ref={messagesEndRef} />
          </Box>

          <Divider />
          <Box display="flex" gap={1} p={1.5}>
            <TextField
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSendMessage()
                }
              }}
              placeholder={t('agents.sessions.chatPlaceholder')}
              fullWidth
              size="small"
              multiline
              maxRows={4}
              disabled={!connected}
            />
            <Button
              variant="contained"
              onClick={handleSendMessage}
              disabled={!chatInput.trim() || !connected}
              endIcon={<SendIcon />}
            >
              {t('agents.sessions.send')}
            </Button>
          </Box>
        </Paper>
      )}

      {/* Task Agent Result */}
      {!isConversational && session.status === 'completed' && session.output_data && (
        <Paper sx={{ p: 3 }}>
          <Typography variant="h6" mb={2}>{t('agents.sessions.result')}</Typography>
          {typeof session.output_data === 'object' &&
          'markdown' in session.output_data &&
          typeof session.output_data.markdown === 'string' ? (
            <Box
              sx={{
                '& p': { mb: 1 },
                '& code': { fontFamily: 'monospace', bgcolor: 'grey.100', px: 0.5, borderRadius: 0.5 },
                '& pre': { bgcolor: 'grey.100', p: 2, borderRadius: 1, overflow: 'auto' },
              }}
              dangerouslySetInnerHTML={{ __html: session.output_data.markdown }}
            />
          ) : (
            <Box
              component="pre"
              sx={{
                bgcolor: 'grey.50',
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 2,
                overflow: 'auto',
                fontSize: 13,
                fontFamily: 'monospace',
              }}
            >
              {JSON.stringify(session.output_data, null, 2)}
            </Box>
          )}
        </Paper>
      )}

      {/* Conversation History (read-only, for completed conversational sessions) */}
      {session.conversation_history && session.conversation_history.length > 0 && isTerminal && (
        <Paper sx={{ p: 3, mt: 3 }}>
          <Typography variant="h6" mb={2}>{t('agents.sessions.conversationHistory')}</Typography>
          <Box display="flex" flexDirection="column" gap={1.5}>
            {session.conversation_history.map((msg, idx) => (
              <Box
                key={idx}
                alignSelf={msg.role === 'user' ? 'flex-end' : 'flex-start'}
                sx={{ maxWidth: '80%' }}
              >
                <Typography variant="caption" color="text.secondary" display="block" mb={0.25}
                  textAlign={msg.role === 'user' ? 'right' : 'left'}>
                  {msg.role}
                </Typography>
                <Paper
                  variant="outlined"
                  sx={{
                    px: 1.5,
                    py: 1,
                    bgcolor: msg.role === 'user' ? 'primary.50' : msg.role === 'tool' ? 'grey.100' : 'background.paper',
                    borderRadius: 2,
                  }}
                >
                  <Typography
                    variant="body2"
                    sx={{ whiteSpace: 'pre-wrap', fontFamily: msg.role === 'tool' ? 'monospace' : undefined }}
                  >
                    {msg.content}
                  </Typography>
                </Paper>
              </Box>
            ))}
          </Box>
        </Paper>
      )}

      {/* Queued / Running state for task agents */}
      {!isConversational && !isTerminal && (
        <Paper sx={{ p: 3, textAlign: 'center' }}>
          <CircularProgress sx={{ mb: 2 }} />
          <Typography color="text.secondary">
            {session.status === 'queued'
              ? t('agents.sessions.statusQueued')
              : t('agents.sessions.statusRunning')}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {t('agents.sessions.pollingHint')}
          </Typography>
        </Paper>
      )}

      <SessionExecutionLogsDialog
        open={showLogs}
        sessionId={id ?? null}
        onClose={() => setShowLogs(false)}
      />

      {/* Execution Log — collapsible, shows system instruction + user prompt */}
      <Paper sx={{ p: 3, mt: 3 }}>
        <Box
          display="flex"
          justifyContent="space-between"
          alignItems="center"
          onClick={() => setExecLogExpanded((v) => !v)}
          sx={{ cursor: 'pointer', userSelect: 'none' }}
        >
          <Typography variant="h6">{t('agents.sessions.executionLog.title')}</Typography>
          <ExpandMoreIcon
            sx={{
              transform: execLogExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
            }}
          />
        </Box>
        <Collapse in={execLogExpanded}>
          <Divider sx={{ my: 2 }} />
          {execLogsLoading ? (
            <CircularProgress size={16} />
          ) : execLogs.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              {t('agents.sessions.executionLog.empty')}
            </Typography>
          ) : (
            execLogs.map((log) => (
              <Box key={log.id} display="flex" flexDirection="column" gap={2}>
                {log.system_instruction != null && (
                  <Box>
                    <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                      <Typography variant="caption" color="text.secondary" fontWeight={600}>
                        {t('agents.sessions.executionLog.systemInstruction')}
                      </Typography>
                      <Tooltip title={t('agents.sessions.executionLog.copy')}>
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation()
                            void navigator.clipboard.writeText(log.system_instruction ?? '')
                          }}
                        >
                          <ContentCopyIcon fontSize="inherit" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                    <Box
                      component="pre"
                      sx={{
                        bgcolor: 'grey.50',
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 2,
                        overflow: 'auto',
                        fontSize: 13,
                        fontFamily: 'monospace',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        m: 0,
                      }}
                    >
                      {log.system_instruction}
                    </Box>
                  </Box>
                )}
                {log.user_prompt != null && (
                  <Box>
                    <Box display="flex" alignItems="center" gap={1} mb={0.5}>
                      <Typography variant="caption" color="text.secondary" fontWeight={600}>
                        {t('agents.sessions.executionLog.userPrompt')}
                      </Typography>
                      <Tooltip title={t('agents.sessions.executionLog.copy')}>
                        <IconButton
                          size="small"
                          onClick={(e) => {
                            e.stopPropagation()
                            void navigator.clipboard.writeText(log.user_prompt ?? '')
                          }}
                        >
                          <ContentCopyIcon fontSize="inherit" />
                        </IconButton>
                      </Tooltip>
                    </Box>
                    <Box
                      component="pre"
                      sx={{
                        bgcolor: 'grey.50',
                        border: 1,
                        borderColor: 'divider',
                        borderRadius: 1,
                        p: 2,
                        overflow: 'auto',
                        fontSize: 13,
                        fontFamily: 'monospace',
                        whiteSpace: 'pre-wrap',
                        wordBreak: 'break-word',
                        m: 0,
                      }}
                    >
                      {log.user_prompt}
                    </Box>
                  </Box>
                )}
              </Box>
            ))
          )}
        </Collapse>
      </Paper>
    </Box>
  )
}
