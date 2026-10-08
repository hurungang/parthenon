import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  IconButton,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import AddIcon from '@mui/icons-material/Add'
import type { DecisionQuestionType, DecisionToolQuestion } from '../../api/decisionToolsApi'

/** Criteria editor for a Choice question: ordered option key/description rows. */
function ChoiceOptionsEditor({
  options,
  onChange,
}: {
  options: Record<string, string>
  onChange: (next: Record<string, string>) => void
}) {
  const { t } = useTranslation()
  const entries = Object.entries(options)
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {t('decisionTools.choiceOptions')}
      </Typography>
      {entries.map(([key, description], idx) => (
        <Stack key={idx} direction="row" spacing={1} alignItems="center" mt={0.5}>
          <TextField
            size="small"
            label={t('decisionTools.optionKey')}
            value={key}
            onChange={(e) => {
              const next: Record<string, string> = {}
              entries.forEach(([k, v], i) => {
                next[i === idx ? e.target.value : k] = v
              })
              onChange(next)
            }}
            sx={{ width: 180 }}
          />
          <TextField
            size="small"
            label={t('decisionTools.optionDescription')}
            value={description}
            fullWidth
            onChange={(e) => onChange({ ...options, [key]: e.target.value })}
          />
          <Tooltip title={t('decisionTools.removeQuestion')}>
            <IconButton
              size="small"
              onClick={() => {
                const next = { ...options }
                delete next[key]
                onChange(next)
              }}
            >
              <DeleteIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
      ))}
      <Box mt={0.5}>
        <Button
          size="small"
          startIcon={<AddIcon fontSize="small" />}
          onClick={() => onChange({ ...options, '': '' })}
        >
          {t('decisionTools.addOption')}
        </Button>
      </Box>
    </Box>
  )
}

/** Criteria editor for a Score question: ordered rubric legend lines. */
function ScoreLegendEditor({
  legend,
  onChange,
}: {
  legend: string[]
  onChange: (next: string[]) => void
}) {
  const { t } = useTranslation()
  return (
    <TextField
      size="small"
      fullWidth
      multiline
      minRows={2}
      label={t('decisionTools.scoreLegend')}
      value={legend.join('\n')}
      onChange={(e) =>
        onChange(e.target.value.split('\n').filter((l) => l.trim().length > 0))
      }
      helperText={t('decisionTools.scoreLegend')}
    />
  )
}

/**
 * Per-question typed editing for one decision tool question
 * (Choice / Score / Noul with instructions and type-appropriate criteria).
 */
export function DecisionToolQuestionEditor({
  question,
  onChange,
  onRemove,
}: {
  question: DecisionToolQuestion
  onChange: (next: DecisionToolQuestion) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const qtype = question.question_type

  return (
    <Box
      border={1}
      borderColor="divider"
      borderRadius={1}
      p={1.5}
      mt={1}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <TextField
          size="small"
          label={t('decisionTools.questionKey')}
          value={question.question_key}
          required
          sx={{ width: 220 }}
          onChange={(e) => onChange({ ...question, question_key: e.target.value })}
        />
        <TextField
          size="small"
          select
          label={t('decisionTools.questionType')}
          value={qtype}
          sx={{ width: 140 }}
          onChange={(e) => {
            const nextType = e.target.value as DecisionQuestionType
            const criteria =
              nextType === 'choice'
                ? { '': '' }
                : nextType === 'score'
                  ? []
                  : null
            onChange({ ...question, question_type: nextType, criteria_options: criteria })
          }}
        >
          <MenuItem value="choice">{t('decisionTools.questionTypes.choice')}</MenuItem>
          <MenuItem value="score">{t('decisionTools.questionTypes.score')}</MenuItem>
          <MenuItem value="noul">{t('decisionTools.questionTypes.noul')}</MenuItem>
        </TextField>
        <Box flexGrow={1} />
        <Tooltip title={t('decisionTools.removeQuestion')}>
          <IconButton size="small" onClick={onRemove}>
            <DeleteIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
      <TextField
        size="small"
        fullWidth
        margin="normal"
        label={t('decisionTools.instructions')}
        value={question.instructions ?? ''}
        onChange={(e) => onChange({ ...question, instructions: e.target.value })}
      />
      {qtype === 'choice' && (
        <ChoiceOptionsEditor
          options={(question.criteria_options as Record<string, string>) ?? {}}
          onChange={(next) => onChange({ ...question, criteria_options: next })}
        />
      )}
      {qtype === 'score' && (
        <Box mt={1}>
          <ScoreLegendEditor
            legend={(question.criteria_options as string[]) ?? []}
            onChange={(next) => onChange({ ...question, criteria_options: next })}
          />
        </Box>
      )}
      {qtype === 'noul' && (
        <Typography variant="caption" color="text.secondary">
          {t('decisionTools.noulHint')}
        </Typography>
      )}
      <FormControlLabel
        sx={{ mt: 1 }}
        control={
          <Checkbox
            checked={question.is_required}
            onChange={(e) => onChange({ ...question, is_required: e.target.checked })}
          />
        }
        label={t('decisionTools.required')}
      />
    </Box>
  )
}
