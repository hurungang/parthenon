import { useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  TextField,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
  Alert,
  CircularProgress,
  IconButton,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import BlockIcon from '@mui/icons-material/Block'
import { useApiKeys } from '../../hooks/useApiKeys'
import { ApiKeyStatus, type ApiKey } from '../../types/apiKeys'
import { CreateApiKeyDialog } from './CreateApiKeyDialog'
import { RevokeApiKeyDialog } from './RevokeApiKeyDialog'

export function ApiKeyListPage() {
  const { t } = useTranslation()
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<ApiKey | null>(null)

  const { data: keys, isLoading, isError, error, refetch } = useApiKeys(
    statusFilter !== 'all' ? statusFilter : undefined,
  )

  const filteredKeys = useMemo(() => {
    if (!keys) return []
    if (!searchTerm.trim()) return keys
    const lower = searchTerm.toLowerCase()
    return keys.filter(
      (k) =>
        k.name.toLowerCase().includes(lower) ||
        k.agent_identity_name.toLowerCase().includes(lower) ||
        k.agent_role_name.toLowerCase().includes(lower),
    )
  }, [keys, searchTerm])

  const handleCreated = () => {
    setCreateOpen(false)
    refetch()
  }

  const handleRevoked = () => {
    setRevokeTarget(null)
    refetch()
  }

  const formatRelativeTime = (dateStr: string | null): string => {
    if (!dateStr) return t('apiKeys.never')
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    if (diffMins < 1) return t('apiKeys.justNow')
    if (diffMins < 60) return t('apiKeys.minutesAgo', { count: diffMins })
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return t('apiKeys.hoursAgo', { count: diffHours })
    const diffDays = Math.floor(diffHours / 24)
    if (diffDays < 7) return t('apiKeys.daysAgo', { count: diffDays })
    return date.toLocaleDateString()
  }

  return (
    <Box p={3}>
      {/* Header */}
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={1}>
        <Typography variant="h4">{t('apiKeys.title')}</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
        >
          {t('apiKeys.createKey')}
        </Button>
      </Box>

      <Typography variant="body1" color="text.secondary" mb={2}>
        {t('apiKeys.subtitle')}
      </Typography>

      {/* Info banner */}
      <Alert severity="info" sx={{ mb: 2 }}>
        {t('apiKeys.infoBanner')}
      </Alert>

      {/* Filter bar */}
      <Box display="flex" gap={2} mb={3} flexWrap="wrap">
        <FormControl size="small" sx={{ minWidth: 140 }}>
          <InputLabel>{t('app.status')}</InputLabel>
          <Select
            value={statusFilter}
            label={t('app.status')}
            onChange={(e) => setStatusFilter(e.target.value)}
          >
            <MenuItem value="all">{t('apiKeys.filterAll')}</MenuItem>
            <MenuItem value="active">{t('apiKeys.filterActive')}</MenuItem>
            <MenuItem value="revoked">{t('apiKeys.filterRevoked')}</MenuItem>
          </Select>
        </FormControl>
        <TextField
          size="small"
          placeholder={t('app.search')}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          sx={{ minWidth: 260 }}
        />
      </Box>

      {/* Loading state */}
      {isLoading && (
        <Box display="flex" justifyContent="center" py={6}>
          <CircularProgress />
        </Box>
      )}

      {/* Error state */}
      {isError && (
        <Alert severity="error" action={<Button onClick={() => refetch()}>{t('app.refresh')}</Button>}>
          {error instanceof Error ? error.message : t('app.error')}
        </Alert>
      )}

      {/* Empty state */}
      {!isLoading && !isError && filteredKeys.length === 0 && (
        <Box textAlign="center" py={6}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            {t('apiKeys.emptyTitle')}
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={2}>
            {t('apiKeys.emptyDescription')}
          </Typography>
          <Button variant="outlined" onClick={() => setCreateOpen(true)}>
            {t('apiKeys.createFirstKey')}
          </Button>
        </Box>
      )}

      {/* Key table */}
      {!isLoading && !isError && filteredKeys.length > 0 && (
        <TableContainer component={Paper} variant="outlined">
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>{t('app.name')}</TableCell>
                <TableCell>{t('apiKeys.agentIdentity')}</TableCell>
                <TableCell>{t('apiKeys.agentRole')}</TableCell>
                <TableCell>{t('app.status')}</TableCell>
                <TableCell>{t('apiKeys.keyHint')}</TableCell>
                <TableCell>{t('app.createdAt')}</TableCell>
                <TableCell>{t('apiKeys.lastUsed')}</TableCell>
                <TableCell align="right">{t('app.actions')}</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredKeys.map((key) => (
                <TableRow key={key.id} hover>
                  <TableCell sx={{ fontWeight: 500 }}>{key.name}</TableCell>
                  <TableCell>{key.agent_identity_name}</TableCell>
                  <TableCell>{key.agent_role_name}</TableCell>
                  <TableCell>
                    <Chip
                      label={
                        key.status === ApiKeyStatus.Active
                          ? t('app.active')
                          : t('apiKeys.revoked')
                      }
                      color={key.status === ApiKeyStatus.Active ? 'success' : 'error'}
                      size="small"
                    />
                  </TableCell>
                  <TableCell>
                    <Typography fontFamily="monospace" fontSize="13px">
                      {key.key_prefix}...
                    </Typography>
                  </TableCell>
                  <TableCell>{formatRelativeTime(key.created_at)}</TableCell>
                  <TableCell>{formatRelativeTime(key.last_used_at)}</TableCell>
                  <TableCell align="right">
                    {key.status === ApiKeyStatus.Active && (
                      <IconButton
                        color="error"
                        size="small"
                        onClick={() => setRevokeTarget(key)}
                        title={t('apiKeys.revoke')}
                      >
                        <BlockIcon fontSize="small" />
                      </IconButton>
                    )}
                    <IconButton
                      color="default"
                      size="small"
                      title={t('app.delete')}
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Dialogs */}
      <CreateApiKeyDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
      />

      <RevokeApiKeyDialog
        keyData={revokeTarget}
        open={!!revokeTarget}
        onClose={() => setRevokeTarget(null)}
        onRevoked={handleRevoked}
      />
    </Box>
  )
}
