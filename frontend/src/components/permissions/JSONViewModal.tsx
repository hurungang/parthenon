import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import CheckIcon from '@mui/icons-material/Check'
import { useRole } from '../../hooks/usePermissions'
import type { PolicyStatement } from '../../types/permissions'

interface JSONViewModalProps {
  open: boolean
  roleId: string
  roleName: string
  onClose: () => void
}

function buildPolicyJson(roleId: string, roleName: string, policies: PolicyStatement[]) {
  return {
    role_id: roleId,
    name: roleName,
    statements: policies.map((p) => ({
      effect: p.effect,
      resource_type: p.module,
      actions: p.actions.map((a) => a.action),
      conditions: {
        tags: Object.fromEntries(p.tag_conditions.map((tc) => [tc.tag_key, tc.tag_value])),
      },
    })),
  }
}

export default function JSONViewModal({
  open,
  roleId,
  roleName,
  onClose,
}: JSONViewModalProps) {
  const { t } = useTranslation()
  const { data: role, isLoading } = useRole(roleId)
  const [copied, setCopied] = useState(false)

  const jsonText = role?.policy_statements
    ? JSON.stringify(buildPolicyJson(roleId, roleName, role.policy_statements), null, 2)
    : ''

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard API unavailable; silently ignore
    }
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        <Box display="flex" justifyContent="space-between" alignItems="center">
          <Typography variant="h6">
            {t('permissions.roles.jsonView')} — {roleName}
          </Typography>
          <Tooltip title={copied ? t('app.copied') : t('app.copy')}>
            <IconButton onClick={handleCopy} size="small" disabled={!jsonText}>
              {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
      </DialogTitle>
      <DialogContent>
        {isLoading ? (
          <CircularProgress size={24} />
        ) : (
          <Paper
            component="pre"
            sx={{
              p: 2,
              bgcolor: 'grey.900',
              color: 'grey.100',
              fontFamily: 'monospace',
              fontSize: '0.8rem',
              overflowX: 'auto',
              borderRadius: 1,
              m: 0,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {jsonText}
          </Paper>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}
