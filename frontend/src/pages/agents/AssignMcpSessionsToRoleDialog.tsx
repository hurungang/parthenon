import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Typography,
} from '@mui/material'
import { useQuery } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import type { AgentRole } from '../../types'

interface McpSessionInfo {
  id: string
  name: string
  server_id: string
  server_name: string
  server_slug: string
}

interface AssignMcpSessionsToRoleDialogProps {
  open: boolean
  role: AgentRole | null
  onClose: () => void
  onSaved: () => Promise<void>
}

/**
 * Dialog to assign MCP Sessions to an AgentRole.
 * 
 * Fetches available sessions (filtered by servers whose tools the role uses),
 * pre-selects already assigned sessions, and submits changes.
 * 
 * Enforces one-session-per-server constraint on the backend.
 */
export function AssignMcpSessionsToRoleDialog({
  open,
  role,
  onClose,
  onSaved,
}: AssignMcpSessionsToRoleDialogProps) {
  const { t } = useTranslation()
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  // Get available MCP sessions (filtered by role's tool usage)
  const { data: availableSessions, isLoading: loadingAvailable } = useQuery<McpSessionInfo[]>({
    queryKey: ['agents', 'roles', role?.id, 'available-mcp-sessions'],
    queryFn: async () => {
      const { data } = await apiClient.get<McpSessionInfo[]>(
        `/agents/roles/${role!.id}/available-mcp-sessions`,
      )
      return data
    },
    enabled: open && !!role?.id,
  })

  // Get currently assigned MCP sessions
  const { data: assignedSessions, isLoading: loadingAssigned } = useQuery<McpSessionInfo[]>({
    queryKey: ['agents', 'roles', role?.id, 'mcp-sessions'],
    queryFn: async () => {
      const { data} = await apiClient.get<McpSessionInfo[]>(`/agents/roles/${role!.id}/mcp-sessions`)
      return data
    },
    enabled: open && !!role?.id,
  })

  useEffect(() => {
    if (open && assignedSessions) {
      setSelectedIds(assignedSessions.map((s) => s.id))
      setDialogError(null)
    }
  }, [open, assignedSessions])

  const toggle = (sessionId: string, serverSlug: string) => {
    setSelectedIds((prev) => {
      if (prev.includes(sessionId)) {
        // Deselect this session
        return prev.filter((id) => id !== sessionId)
      } else {
        // Select this session, but first remove any other session from the same server
        const sessionsFromSameServer = (availableSessions ?? [])
          .filter((s) => s.server_slug === serverSlug)
          .map((s) => s.id)
        return [...prev.filter((id) => !sessionsFromSameServer.includes(id)), sessionId]
      }
    })
  }

  const handleSave = async () => {
    if (!role) return
    try {
      setSaving(true)
      setDialogError(null)

      const previousIds = (assignedSessions ?? []).map((s) => s.id)

      // Sessions to add
      const toAdd = selectedIds.filter((id) => !previousIds.includes(id))
      // Sessions to remove
      const toRemove = previousIds.filter((id) => !selectedIds.includes(id))

      // Add new sessions
      for (const sessionId of toAdd) {
        await apiClient.post(`/agents/roles/${role.id}/mcp-sessions`, {
          mcp_session_id: sessionId,
        })
      }

      // Remove sessions
      for (const sessionId of toRemove) {
        await apiClient.delete(`/agents/roles/${role.id}/mcp-sessions/${sessionId}`)
      }

      await onSaved()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const isLoading = loadingAvailable || loadingAssigned

  // Group available sessions by server
  const sessionsByServer = (availableSessions ?? []).reduce(
    (acc, session) => {
      if (!acc[session.server_slug]) {
        acc[session.server_slug] = {
          serverName: session.server_name,
          sessions: [],
        }
      }
      acc[session.server_slug].sessions.push(session)
      return acc
    },
    {} as Record<string, { serverName: string; sessions: McpSessionInfo[] }>,
  )

  return (
    <Dialog open={open} onClose={() => { onClose(); setDialogError(null) }} maxWidth="lg" fullWidth>
      <DialogTitle>
        {t('agents.roles.assignMcpSessionsTitle', { name: role?.name ?? '' })}
      </DialogTitle>

      <DialogContent dividers>
        {dialogError ? (
          <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />
        ) : null}

        {isLoading ? (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        ) : Object.keys(sessionsByServer).length === 0 ? (
          <Typography color="text.secondary">{t('agents.roles.noAvailableMcpSessions')}</Typography>
        ) : (
          <Box>
            <Typography variant="body2" color="text.secondary" mb={2}>
              {t('agents.roles.assignMcpSessionsHint')}
            </Typography>
            <Box sx={{ maxHeight: 400, overflow: 'auto' }}>
              {Object.entries(sessionsByServer).map(([serverSlug, { serverName, sessions }]) => (
                <Box key={serverSlug} sx={{ mb: 3 }}>
                  <Typography variant="subtitle2" fontWeight="bold" mb={1}>
                    {serverName} ({serverSlug})
                  </Typography>
                  <Box
                    sx={{
                      border: 1,
                      borderColor: 'divider',
                      borderRadius: 1,
                      p: 1,
                      ml: 2,
                    }}
                  >
                    {sessions.map((session) => (
                      <FormControlLabel
                        key={session.id}
                        control={
                          <Checkbox
                            size="small"
                            checked={selectedIds.includes(session.id)}
                            onChange={() => toggle(session.id, serverSlug)}
                          />
                        }
                        label={
                          <Box>
                            <Typography variant="body2">{session.name}</Typography>
                            {selectedIds.includes(session.id) && (
                              <Typography variant="caption" color="primary">
                                {t('agents.roles.selectedForServer')}
                              </Typography>
                            )}
                          </Box>
                        }
                        sx={{ display: 'block', my: 0.5 }}
                      />
                    ))}
                  </Box>
                </Box>
              ))}
            </Box>
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={() => { onClose(); setDialogError(null) }} disabled={saving}>
          {t('app.cancel')}
        </Button>
        <Button variant="contained" onClick={handleSave} disabled={saving || isLoading}>
          {saving ? t('app.saving') : t('app.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
