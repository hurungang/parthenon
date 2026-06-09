import { useState } from 'react'
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
  FormControlLabel,
  IconButton,
  Paper,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import VisibilityIcon from '@mui/icons-material/Visibility'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { usePagination } from '../../hooks/usePagination'
import PermissionDeniedAlert from '../../components/permissions/PermissionDeniedAlert'
import { SkillEditor } from './SkillEditor'
import type { Skill } from '../../types'

/**
 * Skill list page with inline SkillEditor side panel.
 *
 * editorSkill:
 *   undefined → editor hidden
 *   null      → create mode
 *   Skill     → edit mode
 */
export function SkillListPage() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const pag = usePagination()
  const [search, setSearch] = useState('')
  const [editorSkill, setEditorSkill] = useState<Skill | null | undefined>(undefined)
  const [editorMode, setEditorMode] = useState<'create' | 'edit' | 'view'>('create')
  const [deleteTarget, setDeleteTarget] = useState<Skill | null>(null)
  const [showSystem, setShowSystem] = useState(false)

  const { data: skills, isLoading, error } = useQuery<Skill[]>({
    queryKey: ['skills', pag.limit, pag.offset],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills', {
        params: { limit: pag.limit, offset: pag.offset },
      })
      return data
    },
  })

  const filteredSkills = (skills ?? []).filter(
    (s) =>
      (showSystem || !s.is_system) &&
      (!search ||
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        (s.description ?? '').toLowerCase().includes(search.toLowerCase())),
  )

  const handleDelete = async (id: string) => {
    await apiClient.delete(`/skills/${id}`)
    setDeleteTarget(null)
    await queryClient.invalidateQueries({ queryKey: ['skills'] })
  }

  return (
    <Box>
      {/* Main list */}
      <Box>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h4" fontWeight={700}>
            {t('skills.title')}
          </Typography>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setEditorMode('create')
              setEditorSkill(null)
            }}
          >
            {t('skills.createSkill')}
          </Button>
        </Box>

        <Box display="flex" alignItems="center" gap={2} mb={2}>
          <TextField
            placeholder={t('app.search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            size="small"
            sx={{ width: 320 }}
          />
          <FormControlLabel
            control={<Switch size="small" checked={showSystem} onChange={(e) => setShowSystem(e.target.checked)} />}
            label={t('skills.showSystem')}
          />
        </Box>

        {isLoading && <CircularProgress />}
        {error && <PermissionDeniedAlert error={error} fallbackMessage={t('app.error')} />}

        {!isLoading && !error && (
          <TableContainer component={Paper}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t('app.name')}</TableCell>
                  <TableCell>{t('skills.toolCount')}</TableCell>
                  <TableCell>{t('app.status')}</TableCell>
                  <TableCell>{t('app.actions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filteredSkills.map((skill) => (
                  <TableRow
                    key={skill.id}
                    selected={
                      editorSkill !== null &&
                      editorSkill !== undefined &&
                      editorSkill.id === skill.id
                    }
                  >
                    <TableCell>
                      <Box display="flex" alignItems="center" gap={0.5}>
                        <Typography variant="body2" fontWeight={500}>
                          {skill.name}
                        </Typography>
                        {skill.is_system && (
                          <Chip label={t('skills.systemChip')} size="small" color="info" variant="outlined" sx={{ height: 18, fontSize: '0.65rem' }} />
                        )}
                      </Box>
                      {skill.description && (
                        <Typography variant="caption" color="text.secondary">
                          {skill.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={skill.tool_ids?.length ?? 0}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={skill.is_active ? t('app.active') : t('app.inactive')}
                        color={skill.is_active ? 'success' : 'default'}
                        size="small"
                      />
                    </TableCell>
                    <TableCell>
                      <IconButton
                        size="small"
                        onClick={() => {
                          setEditorMode('view')
                          setEditorSkill(skill)
                        }}
                      >
                        <VisibilityIcon fontSize="small" />
                      </IconButton>
                      {!skill.is_system && (
                        <>
                          <IconButton
                            size="small"
                            onClick={() => {
                              setEditorMode('edit')
                              setEditorSkill(skill)
                            }}
                          >
                            <EditIcon fontSize="small" />
                          </IconButton>
                          <IconButton size="small" onClick={() => setDeleteTarget(skill)}>
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {filteredSkills.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} align="center">
                      {t('app.noData')}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        {!isLoading && !error && (
          <TablePagination
            component="div"
            count={-1}
            page={pag.page}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        )}
      </Box>

      <SkillEditor
        open={editorSkill !== undefined}
        skill={editorSkill ?? null}
        mode={editorMode}
        onClose={() => setEditorSkill(undefined)}
        onSaved={() => setEditorSkill(undefined)}
      />

      <Dialog open={deleteTarget !== null} onClose={() => setDeleteTarget(null)}>
        <DialogTitle>{t('skills.deleteTitle')}</DialogTitle>
        <DialogContent>
          <Typography>{t('skills.deleteConfirm', { name: deleteTarget?.name })}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteTarget(null)}>{t('app.cancel')}</Button>
          <Button
            variant="contained"
            color="error"
            onClick={() => deleteTarget && handleDelete(deleteTarget.id)}
          >
            {t('app.delete')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
