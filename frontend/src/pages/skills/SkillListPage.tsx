import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
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
  const [search, setSearch] = useState('')
  const [editorSkill, setEditorSkill] = useState<Skill | null | undefined>(undefined)

  const { data: skills, isLoading, error } = useQuery<Skill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      const { data } = await apiClient.get<Skill[]>('/skills')
      return data
    },
  })

  const filteredSkills = (skills ?? []).filter(
    (s) =>
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description ?? '').toLowerCase().includes(search.toLowerCase()),
  )

  const handleDelete = async (id: string) => {
    if (confirm(t('app.confirm'))) {
      await apiClient.delete(`/skills/${id}`)
      await queryClient.invalidateQueries({ queryKey: ['skills'] })
    }
  }

  return (
    <Box display="flex" gap={2} alignItems="flex-start">
      {/* Main list */}
      <Box flex={1} minWidth={0}>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h4" fontWeight={700}>
            {t('skills.title')}
          </Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setEditorSkill(null)}>
            {t('skills.createSkill')}
          </Button>
        </Box>

        <TextField
          placeholder={t('app.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          sx={{ mb: 2, width: 320 }}
        />

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
                      <Typography variant="body2" fontWeight={500}>
                        {skill.name}
                      </Typography>
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
                      <IconButton size="small" onClick={() => setEditorSkill(skill)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                      <IconButton size="small" onClick={() => handleDelete(skill.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
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
      </Box>

      {/* In-page editor panel */}
      {editorSkill !== undefined && (
        <SkillEditor
          skill={editorSkill}
          onClose={() => setEditorSkill(undefined)}
          onSaved={() => setEditorSkill(undefined)}
        />
      )}
    </Box>
  )
}
