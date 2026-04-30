import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useTagDefinitions, useCreateTag, useUpdateTag, useDeleteTag } from '../../hooks/usePermissions'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { TagScope } from '../../types/permissions'
import type { TagDefinition } from '../../types/permissions'

type DialogMode = 'add' | 'edit' | null

interface TagForm {
  key: string
  scope: TagScope
  resource_type: string
  description: string
  allowed_values: string[]
  valueInput: string
}

const emptyForm: TagForm = {
  key: '',
  scope: TagScope.Global,
  resource_type: '',
  description: '',
  allowed_values: [],
  valueInput: '',
}

export function TagsPage() {
  const { t } = useTranslation()
  const { data: tags, isLoading, error } = useTagDefinitions()
  const createTag = useCreateTag()
  const updateTag = useUpdateTag()
  const deleteTag = useDeleteTag()

  const [dialogMode, setDialogMode] = useState<DialogMode>(null)
  const [dialogError, setDialogError] = useState<unknown>(null)
  const [editingTag, setEditingTag] = useState<TagDefinition | null>(null)
  const [form, setForm] = useState<TagForm>(emptyForm)
  const [deleteTarget, setDeleteTarget] = useState<TagDefinition | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  const openAdd = () => {
    setForm(emptyForm)
    setEditingTag(null)
    setDialogError(null)
    setDialogMode('add')
  }

  const openEdit = (tag: TagDefinition) => {
    setEditingTag(tag)
    setForm({
      key: tag.key,
      scope: tag.scope,
      resource_type: tag.resource_type ?? '',
      description: tag.description ?? '',
      allowed_values: tag.allowed_values.map((v) => v.value),
      valueInput: '',
    })
    setDialogError(null)
    setDialogMode('edit')
  }

  const addValue = () => {
    const v = form.valueInput.trim()
    if (!v || form.allowed_values.includes(v)) {
      console.log('Tag value not added:', !v ? 'empty value' : 'duplicate value')
      return
    }
    console.log('Adding tag value:', v)
    setForm((f) => ({ ...f, allowed_values: [...f.allowed_values, v], valueInput: '' }))
  }

  const canAddValue = () => {
    const v = form.valueInput.trim()
    return v.length > 0 && !form.allowed_values.includes(v)
  }

  const removeValue = (v: string) => {
    setForm((f) => ({ ...f, allowed_values: f.allowed_values.filter((x) => x !== v) }))
  }

  const handleSave = async () => {
    try {
      setDialogError(null)
      if (dialogMode === 'add') {
        await createTag.mutateAsync({
          key: form.key,
          scope: form.scope,
          resource_type: form.scope === TagScope.ResourceType ? form.resource_type : undefined,
          description: form.description || undefined,
          allowed_values: form.allowed_values,
        })
      } else if (dialogMode === 'edit' && editingTag) {
        const currentValues = editingTag.allowed_values.map((v) => v.value)
        const addValues = form.allowed_values.filter((v) => !currentValues.includes(v))
        const removeValues = currentValues.filter((v) => !form.allowed_values.includes(v))
        await updateTag.mutateAsync({
          id: editingTag.id,
          data: {
            description: form.description || undefined,
            add_values: addValues,
            remove_values: removeValues,
          },
        })
      }
      setDialogMode(null)
    } catch (err) {
      setDialogError(err)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleteError(null)
    try {
      await deleteTag.mutateAsync(deleteTarget.id)
      setDeleteTarget(null)
    } catch {
      setDeleteError(t('permissions.tags.conflictError'))
    }
  }

  const filtered = (tags ?? []).filter(
    (t) => !search || t.key.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <Box>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
        <Typography variant="h6">{t('permissions.tags.title')}</Typography>
        <Button variant="contained" startIcon={<AddIcon />} onClick={openAdd}>
          {t('permissions.tags.addTag')}
        </Button>
      </Box>

      <TextField
        size="small"
        placeholder={t('app.search')}
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        sx={{ mb: 2, width: 300 }}
      />

      {isLoading && <CircularProgress />}
      {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

      <TableContainer component={Paper}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('permissions.tags.key')}</TableCell>
              <TableCell>{t('permissions.tags.scope')}</TableCell>
              <TableCell>{t('permissions.tags.resourceType')}</TableCell>
              <TableCell>{t('permissions.tags.allowedValuesCount')}</TableCell>
              <TableCell>{t('app.createdAt')}</TableCell>
              <TableCell>{t('app.actions')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((tag) => (
              <TableRow key={tag.id}>
                <TableCell>{tag.key}</TableCell>
                <TableCell>
                  {tag.scope === TagScope.Global
                    ? t('permissions.tags.scopeGlobal')
                    : t('permissions.tags.scopeResourceType')}
                </TableCell>
                <TableCell>{tag.resource_type ?? '—'}</TableCell>
                <TableCell>{tag.allowed_values.length}</TableCell>
                <TableCell>{new Date(tag.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  <Tooltip title={t('app.edit')}>
                    <IconButton size="small" onClick={() => openEdit(tag)}>
                      <EditIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                  <Tooltip title={t('app.delete')}>
                    <IconButton size="small" onClick={() => { setDeleteTarget(tag); setDeleteError(null) }}>
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Add / Edit dialog */}
      <Dialog open={dialogMode !== null} onClose={() => { setDialogMode(null); setDialogError(null) }} maxWidth="sm" fullWidth>
        <DialogTitle>
          {dialogMode === 'add' ? t('permissions.tags.addTag') : t('permissions.tags.editTag')}
        </DialogTitle>
        <DialogContent>
          {dialogError ? <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} /> : null}
          <Stack spacing={2} sx={{ mt: 1 }}>
            <TextField
              label={t('permissions.tags.key')}
              value={form.key}
              onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))}
              disabled={dialogMode === 'edit'}
              required
            />
            <FormControl>
              <InputLabel>{t('permissions.tags.scope')}</InputLabel>
              <Select
                value={form.scope}
                label={t('permissions.tags.scope')}
                onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value as TagScope }))}
                disabled={dialogMode === 'edit'}
              >
                <MenuItem value={TagScope.Global}>{t('permissions.tags.scopeGlobal')}</MenuItem>
                <MenuItem value={TagScope.ResourceType}>{t('permissions.tags.scopeResourceType')}</MenuItem>
              </Select>
            </FormControl>
            {form.scope === TagScope.ResourceType && (
              <TextField
                label={t('permissions.tags.resourceType')}
                value={form.resource_type}
                onChange={(e) => setForm((f) => ({ ...f, resource_type: e.target.value }))}
                disabled={dialogMode === 'edit'}
              />
            )}
            <TextField
              label={t('app.description')}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              multiline
              rows={2}
            />
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                {t('permissions.tags.allowedValues')}
              </Typography>
              <Box display="flex" gap={1} mb={1}>
                <TextField
                  size="small"
                  placeholder={t('permissions.tags.valuePlaceholder')}
                  value={form.valueInput}
                  onChange={(e) => setForm((f) => ({ ...f, valueInput: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addValue() } }}
                  sx={{ flexGrow: 1 }}
                />
                <Button 
                  variant="outlined" 
                  onClick={addValue}
                  disabled={!canAddValue()}
                >
                  {t('permissions.tags.addValue')}
                </Button>
              </Box>
              <Box display="flex" flexWrap="wrap" gap={0.5}>
                {form.allowed_values.map((v) => (
                  <Chip key={v} label={v} onDelete={() => removeValue(v)} size="small" />
                ))}
              </Box>
            </Box>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialogMode(null)}>{t('app.cancel')}</Button>
          <Button
            onClick={handleSave}
            variant="contained"
            disabled={createTag.isPending || updateTag.isPending}
          >
            {t('app.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete confirmation dialog */}
      <Dialog open={!!deleteTarget} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('app.delete')}</DialogTitle>
        <DialogContent>
          {deleteError ? (
            <Alert severity="error">{deleteError}</Alert>
          ) : (
            <Typography>
              {t('permissions.tags.deleteConfirm', { key: deleteTarget?.key })}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('app.cancel')}</Button>
          {!deleteError && (
            <Button
              color="error"
              variant="contained"
              onClick={handleDelete}
              disabled={deleteTag.isPending}
            >
              {t('app.delete')}
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Box>
  )
}
