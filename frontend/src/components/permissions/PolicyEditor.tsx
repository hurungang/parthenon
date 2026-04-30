import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import { useRole, useDeletePolicyStatement } from '../../hooks/usePermissions'
import PermissionDeniedAlert from './PermissionDeniedAlert'
import AddStatementDialog from './AddStatementDialog'
import type { PolicyStatement } from '../../types/permissions'
import { PolicyEffect } from '../../types/permissions'

interface PolicyEditorProps {
  roleId: string
}

export default function PolicyEditor({ roleId }: PolicyEditorProps) {
  const { t } = useTranslation()
  const { data: role, isLoading } = useRole(roleId)
  const deleteStatement = useDeletePolicyStatement()

  const [addOpen, setAddOpen] = useState(false)
  const [deleteErrors, setDeleteErrors] = useState<Record<string, unknown>>({})
  const [editingPolicy, setEditingPolicy] = useState<PolicyStatement | null>(null)
  const handleRemove = async (policy: PolicyStatement) => {
    try {
      setDeleteErrors((prev) => ({ ...prev, [policy.id]: null }))
      await deleteStatement.mutateAsync({ roleId, policyId: policy.id })
    } catch (err) {
      setDeleteErrors((prev) => ({ ...prev, [policy.id]: err }))
    }
  }

  const handleEdit = (policy: PolicyStatement) => {
    setEditingPolicy(policy)
    setAddOpen(true)
  }

  const handleCloseDialog = () => {
    setAddOpen(false)
    setEditingPolicy(null)
  }

  if (isLoading) return <CircularProgress size={20} />

  const policies = role?.policy_statements ?? []

  return (
    <Box sx={{ p: 1 }}>
      {policies.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          {t('app.noData')}
        </Typography>
      )}

      {policies.map((policy) => (
        <Card key={policy.id} variant="outlined" sx={{ mb: 1.5, border: '1px solid', borderColor: 'divider' }}>
          <CardContent sx={{ pb: '12px !important' }}>
            {deleteErrors[policy.id] != null && (
              <PermissionDeniedAlert
                error={deleteErrors[policy.id]}
                fallbackMessage={t('app.error')}
              />
            )}

            {/* Policy statement in one line: Effect + Actions + Resource Type */}
            <Box display="flex" justifyContent="space-between" alignItems="flex-start" mb={1}>
              <Box display="flex" flexWrap="wrap" gap={0.5} alignItems="center">
                {/* Effect chip */}
                <Chip
                  label={
                    policy.effect === PolicyEffect.Allow
                      ? t('permissions.roles.effectAllow')
                      : t('permissions.roles.effectDeny')
                  }
                  size="small"
                  color={policy.effect === PolicyEffect.Allow ? 'success' : 'error'}
                  sx={{ fontWeight: 600 }}
                />

                {/* Action chips */}
                {policy.actions.map((a) => (
                  <Chip
                    key={a.id}
                    label={a.action}
                    size="small"
                    sx={{ bgcolor: 'grey.100', border: '1px solid', borderColor: 'grey.300', fontWeight: 500 }}
                  />
                ))}

                {/* Resource type chip */}
                <Chip
                  label={policy.module}
                  size="small"
                  sx={{ bgcolor: 'primary.50', color: 'primary.main', border: '1px solid', borderColor: 'primary.200', fontWeight: 600 }}
                />
              </Box>

              {/* Action buttons */}
              <Box display="flex" gap={0.5}>
                <Button
                  size="small"
                  color="primary"
                  variant="text"
                  onClick={() => handleEdit(policy)}
                  disabled={editingPolicy?.id === policy.id && addOpen}
                >
                  {t('app.edit')}
                </Button>
                <Button
                  size="small"
                  color="error"
                  variant="text"
                  onClick={() => handleRemove(policy)}
                  disabled={deleteStatement.isPending}
                >
                  {t('app.delete')}
                </Button>
              </Box>
            </Box>

            {/* Resource IDs section */}
            {policy.resources.length > 0 && (
              <Box mt={1}>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  {t('permissions.roles.resourceIds')}
                </Typography>
                <Box display="flex" flexWrap="wrap" gap={0.5}>
                  {policy.resources.map((res) => (
                    <Chip
                      key={res.id}
                      label={`${res.resource_type}:${res.resource_id ?? '*'}`}
                      size="small"
                      variant="outlined"
                      sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}
                    />
                  ))}
                </Box>
              </Box>
            )}

            {/* Tag conditions section */}
            {policy.tag_conditions.length > 0 && (
              <Box mt={1}>
                <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                  {t('permissions.roles.tagConditions')}
                </Typography>
                <Box display="flex" flexWrap="wrap" gap={0.5}>
                  {policy.tag_conditions.map((tc) => (
                    <Chip
                      key={tc.id}
                      label={`${tc.tag_key}=${tc.tag_value}`}
                      size="small"
                      variant="outlined"
                      sx={{ fontFamily: 'monospace', fontSize: '0.75rem', bgcolor: 'grey.50' }}
                    />
                  ))}
                </Box>
              </Box>
            )}
          </CardContent>
        </Card>
      ))}

      <Button
        size="small"
        variant="outlined"
        startIcon={<AddIcon />}
        onClick={() => {
          setEditingPolicy(null)
          setAddOpen(true)
        }}
        sx={{ mt: 0.5 }}
      >
        {t('permissions.roles.addPolicy')}
      </Button>

      <AddStatementDialog
        open={addOpen}
        roleId={roleId}
        editingPolicy={editingPolicy}
        onClose={handleCloseDialog}
      />
    </Box>
  )
}
