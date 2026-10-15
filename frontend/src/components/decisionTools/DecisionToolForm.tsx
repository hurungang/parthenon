import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import DeleteIcon from '@mui/icons-material/Delete'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import VisibilityIcon from '@mui/icons-material/Visibility'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useDialogErrorHandler } from '../../hooks/useDialogErrorHandler'
import PermissionDeniedAlert from '../permissions/PermissionDeniedAlert'
import {
  createDecisionTool,
  generateDecisionToolDraft,
  updateDecisionTool,
} from '../../api/decisionToolsApi'
import type {
  AgentDataTypeSummary,
  DecisionTool,
  DecisionToolCreate,
  DecisionToolQuestion,
  DecisionToolStatus,
} from '../../api/decisionToolsApi'
import { DecisionToolQuestionEditor } from './DecisionToolQuestionEditor'
import { getSystemOneStatus, listEnabledDecisionModels } from '../../api/systemOneApi'
import type { DecisionEnabledModel, SystemOneStatus } from '../../api/systemOneApi'
import { useDataTypes } from '../../hooks/useDataTypes'
import type { AgentDataType } from '../../types'
import {
  detectStatePlaceholdersFromQuestions,
  resolveStateMapping,
} from '../../utils/decisionStatePaths'
import type { StateMappingRow } from '../../utils/decisionStatePaths'

interface FormState {
  name: string
  purpose: string
  input_data_type_id: string
  output_data_type_id: string
  /** Explicit mappings only (state_key → input property). 1:1 keys need
      no row — they auto-match from the input data type. */
  state_preset: StateMappingRow[]
  act_threshold: number
  confirm_threshold: number
  /** Selected enabled decision model (replaces the legacy provider_model). */
  decision_model_availability_id: string
  status: DecisionToolStatus
  enabled: boolean
  questions: DecisionToolQuestion[]
}

const EMPTY_QUESTION = (): DecisionToolQuestion => ({
  ordering: 0,
  question_key: '',
  question_type: 'choice',
  instructions: '',
  criteria_options: { '': '' },
  is_required: true,
})

const EMPTY_FORM = (): FormState => ({
  name: '',
  purpose: '',
  input_data_type_id: '',
  output_data_type_id: '',
  state_preset: [],
  act_threshold: 0.9,
  confirm_threshold: 0.7,
  decision_model_availability_id: '',
  status: 'active',
  // New tools start as DISABLED drafts: enabling requires input+output
  // data types (pre-validated inline), so drafts save cleanly by default.
  enabled: false,
  questions: [],
})

function formFromTool(tool: DecisionTool): FormState {
  return {
    name: tool.name,
    purpose: tool.purpose ?? '',
    input_data_type_id: tool.input_data_type_id ?? '',
    output_data_type_id: tool.output_data_type_id ?? '',
    // Legacy agent_data mappings (retired source) are dropped here —
    // they disappear on the next save.
    state_preset: Object.entries(tool.state_preset ?? {})
      .filter(([, mapping]) => mapping.source === 'input')
      .map(([state_key, mapping]) => ({
        state_key,
        key: mapping.key,
      })),
    act_threshold: tool.act_threshold,
    confirm_threshold: tool.confirm_threshold,
    decision_model_availability_id:
      tool.decision_model_availability_id ?? '',
    status: tool.status,
    enabled: tool.enabled,
    questions: tool.questions.map((q) => ({ ...q })),
  }
}

/** Read-only viewer for a referenced data type's field definitions. */
function DataTypeViewDialog({
  dataType,
  title,
  onClose,
}: {
  dataType: AgentDataType | null
  title: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  return (
    <Dialog open={dataType != null} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        {dataType?.description && (
          <Typography variant="body2" color="text.secondary" mb={1}>
            {dataType.description}
          </Typography>
        )}
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t('decisionTools.fieldName')}</TableCell>
              <TableCell>{t('decisionTools.fieldType')}</TableCell>
              <TableCell>{t('decisionTools.fieldDescription')}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(dataType?.fields ?? []).map((f) => (
              <TableRow key={f.name}>
                <TableCell>
                  <code>{f.name}</code>
                </TableCell>
                <TableCell>{f.type}</TableCell>
                <TableCell>{f.description ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('app.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}

/**
 * Decision tool authoring form: name (per-tenant uniqueness), purpose,
 * input/output AgentDataType selectors (with read-only viewers), typed
 * question builder (Choice/Score/Noul), guided state preset mapper
 * (backtick state-path auto-detection, input-type-driven property
 * selectors), AI generation button, auto-generated description preview,
 * and act/confirm confidence thresholds.
 */
export function DecisionToolForm({
  open,
  editing,
  onClose,
  onSaved,
}: {
  open: boolean
  editing: DecisionTool | null
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
  const [form, setForm] = useState<FormState>(EMPTY_FORM())
  const [formError, setFormError] = useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [statusInfo, setStatusInfo] = useState<SystemOneStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [enabledModels, setEnabledModels] = useState<DecisionEnabledModel[]>([])
  const [viewingType, setViewingType] = useState<{ type: AgentDataType; title: string } | null>(
    null,
  )

  const { data: dataTypes } = useDataTypes({ page: 1, page_size: 100 })
  const dataTypeList = useMemo(() => dataTypes?.items ?? [], [dataTypes])
  const inputDataType = useMemo(
    () => dataTypeList.find((d) => d.id === form.input_data_type_id) ?? null,
    [dataTypeList, form.input_data_type_id],
  )

  // Configured-model gate: check (once per open) whether a System One
  // provider is configured; authoring is blocked otherwise.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setStatusLoading(true)
    setStatusError(null)
    getSystemOneStatus()
      .then((s) => {
        if (!cancelled) setStatusInfo(s)
        // Selector feed: enabled models only (provider enabled + model
        // enabled), fetched fresh per open to avoid stale selections.
        return listEnabledDecisionModels()
      })
      .then((models) => {
        if (!cancelled) setEnabledModels(models)
      })
      .catch(() => {
        if (!cancelled) setStatusError(t('decisionTools.validation.statusCheckFailed'))
      })
      .finally(() => {
        if (!cancelled) setStatusLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, t])

  useEffect(() => {
    if (open) {
      clearDialogError()
      setFormError(null)
      setForm(editing ? formFromTool(editing) : EMPTY_FORM())
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing])

  const systemOneConfigured = statusInfo?.configured === true

  /** Backtick-quoted state paths detected across question instructions —
      these are the placeholders the tool's prompt/questions use. */
  const detectedPaths = useMemo(
    () =>
      detectStatePlaceholdersFromQuestions(form.questions.map((q) => q.instructions)),
    [form.questions],
  )

  /**
   * The state keys are the detected placeholders plus the explicit
   * mapping keys (e.g. loaded from an existing tool). Each key that
   * equals an input data type field name resolves 1:1 silently; the
   * rest are UNMATCHED and rendered as one mapper row each.
   */
  const placeholders = useMemo(() => {
    const keys: string[] = []
    for (const m of form.state_preset) {
      const k = m.state_key.trim()
      if (k && !keys.includes(k)) keys.push(k)
    }
    for (const p of detectedPaths) {
      if (!keys.includes(p)) keys.push(p)
    }
    return keys
  }, [form.state_preset, detectedPaths])

  const inputFieldNames = useMemo(
    () => (inputDataType?.fields ?? []).map((f) => f.name),
    [inputDataType],
  )

  const { matched, unmatched } = useMemo(
    () => resolveStateMapping(placeholders, form.state_preset, inputFieldNames),
    [placeholders, form.state_preset, inputFieldNames],
  )

  /** Enabling requires both data types — pre-validated inline instead of a
      raw 422: the Save button is disabled with an explanatory hint. */
  const readinessBlocked =
    form.enabled && (!form.input_data_type_id || !form.output_data_type_id)

  /** Client-side preview mirroring the server's generate_tool_description. */
  const descriptionPreview = useMemo(() => {
    const lines: string[] = []
    const title = `Decision tool '${form.name || '…'}'`
    lines.push(
      form.purpose.trim()
        ? `${title}: ${form.purpose.trim()}`
        : `${title}: evaluates predefined questions against a constructed state and returns structured typed answers with confidence.`,
    )
    const inputType = dataTypeList.find((d) => d.id === form.input_data_type_id)
    const outputType = dataTypeList.find((d) => d.id === form.output_data_type_id)
    if (inputType) {
      lines.push(
        '',
        `Input data type: ${inputType.name} (${inputType.slug}). Fields: ${inputType.fields.map((f) => f.name).join(', ')}.`,
      )
    }
    if (outputType) {
      lines.push(`Output data type: ${outputType.name} (${outputType.slug}).`)
    }
    const questions = form.questions.filter((q) => q.question_key.trim())
    if (questions.length > 0) {
      lines.push('', 'Questions:')
      for (const q of questions) {
        let desc = `- \`${q.question_key}\` (${q.question_type})`
        if (q.instructions?.trim()) desc += `: ${q.instructions.trim()}`
        const options = q.criteria_options
        if (options && !Array.isArray(options) && Object.keys(options).length > 0) {
          desc += ` Options: ${Object.keys(options).filter(Boolean).join(', ')}.`
        } else if (Array.isArray(options) && options.length > 0) {
          desc += ` Rubric: ${JSON.stringify(options)}.`
        }
        if (!q.is_required) desc += ' (optional)'
        lines.push(desc)
      }
    }
    const stateKeys = placeholders
    if (stateKeys.length > 0) {
      lines.push('', `State fields sent to the model: ${stateKeys.join(', ')}.`)
    }
    lines.push(
      '',
      `Returns per-question typed answers with probabilities and an overall gate outcome (act >= ${form.act_threshold}, confirm >= ${form.confirm_threshold}, else escalate).`,
    )
    return lines.join('\n')
  }, [form, dataTypeList, placeholders])

  const setQuestions = (questions: DecisionToolQuestion[]) =>
    setForm((f) => ({
      ...f,
      questions: questions.map((q, i) => ({ ...q, ordering: q.ordering || i })),
    }))

  const validate = (): string | null => {
    if (!form.name.trim()) return t('decisionTools.validation.nameRequired')
    if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(form.name.trim()))
      return t('decisionTools.validation.nameFormat')
    if (!form.purpose.trim()) return t('decisionTools.validation.purposeRequired')
    // Questions are optional: with none authored they are auto-derived from
    // the output data type at execution time (override wins).
    const keys = form.questions.map((q) => q.question_key.trim())
    if (keys.some((k) => !k)) return t('decisionTools.validation.questionKeyRequired')
    const dup = keys.find((k, i) => keys.indexOf(k) !== i)
    if (dup) return t('decisionTools.validation.duplicateQuestionKey', { key: dup })
    if (form.act_threshold < form.confirm_threshold)
      return t('decisionTools.validation.thresholdsOrder')
    for (const q of form.questions) {
      if (q.question_type === 'choice') {
        const options = q.criteria_options as Record<string, string> | null
        if (!options || Object.keys(options).filter((k) => k.trim()).length === 0)
          return t('decisionTools.validation.choiceOptionsRequired')
      }
      if (q.question_type === 'score') {
        const legend = q.criteria_options as string[] | null
        if (!legend || legend.length === 0)
          return t('decisionTools.validation.scoreLegendRequired')
      }
    }
    for (const m of form.state_preset) {
      if (!m.state_key.trim() || !m.key.trim())
        return t('decisionTools.validation.stateKeyRequired')
    }
    // Unmatched placeholders need an explicit mapping — surfaced inline as
    // one mapper row per key.
    for (const key of unmatched) {
      const row = form.state_preset.find((m) => m.state_key.trim() === key)
      if (!row || !row.key.trim())
        return t('decisionTools.validation.mapPlaceholder', { key })
    }
    // Model selection: only enabled models are selectable; a selection is
    // required whenever the enabled-models listing is non-empty.
    if (enabledModels.length > 0 && !form.decision_model_availability_id)
      return t('decisionTools.validation.modelRequired')
    if (
      form.decision_model_availability_id &&
      !enabledModels.some(
        (m) => m.availability_id === form.decision_model_availability_id,
      )
    )
      return t('decisionTools.validation.modelUnavailable')
    // Pre-validate the readiness rule — a blocked save shows an inline
    // hint instead of a raw 422.
    if (readinessBlocked) return t('decisionTools.validation.readinessRequiresTypes')
    return null
  }

  const buildPayload = (): DecisionToolCreate => {
    const questions = form.questions.map((q, i) => ({
      ordering: i,
      question_key: q.question_key.trim(),
      question_type: q.question_type,
      instructions: q.instructions?.trim() || null,
      criteria_options:
        q.question_type === 'noul'
          ? null
          : q.question_type === 'choice'
            ? Object.fromEntries(
                Object.entries(
                  (q.criteria_options as Record<string, string>) ?? {},
                ).filter(([k]) => k.trim()),
              )
            : (q.criteria_options as string[]) ?? [],
      is_required: q.is_required,
    }))
    // Only EXPLICIT mappings are saved — 1:1 keys auto-match at
    // execution time (empty preset = passthrough) and are omitted.
    const state_preset = Object.fromEntries(
      form.state_preset
        .filter((m) => m.state_key.trim() && m.key.trim())
        .map((m) => [
          m.state_key.trim(),
          { source: 'input' as const, key: m.key.trim() },
        ]),
    )
    return {
      name: form.name.trim(),
      purpose: form.purpose.trim(),
      input_data_type_id: form.input_data_type_id || null,
      output_data_type_id: form.output_data_type_id || null,
      state_preset: Object.keys(state_preset).length > 0 ? state_preset : null,
      act_threshold: form.act_threshold,
      confirm_threshold: form.confirm_threshold,
      decision_model_availability_id:
        form.decision_model_availability_id || null,
      status: form.status,
      enabled: form.enabled,
      questions,
    }
  }

  const handleGenerate = async () => {
    if (!form.purpose.trim()) {
      setFormError(t('decisionTools.validation.purposeRequired'))
      return
    }
    try {
      clearDialogError()
      setFormError(null)
      setGenerating(true)
      const draft = await generateDecisionToolDraft({
        description: form.purpose.trim(),
        input_data_type_id: form.input_data_type_id || null,
        output_data_type_id: form.output_data_type_id || null,
        existing_questions: editing ? form.questions : null,
      })
      setForm((f) => {
        const draftedStateKeys = Object.keys(draft.state_preset ?? {})
        const existingPreset = f.state_preset.filter((m) =>
          draftedStateKeys.includes(m.state_key),
        )
        // Only input-sourced draft rows are kept (agent_data is retired).
        const presetEntries = Object.entries(draft.state_preset ?? {})
          .filter(([, mapping]) => mapping.source === 'input')
          .map(([state_key, mapping]) => ({
            state_key,
            key: mapping.key,
          }))
        return {
          ...f,
          questions: draft.questions.map((q, i) => ({ ...q, ordering: i })),
          state_preset:
            presetEntries.length > 0 ? presetEntries : existingPreset,
        }
      })
    } catch (err) {
      setDialogError(err)
    } finally {
      setGenerating(false)
    }
  }

  const handleSave = async () => {
    const validationError = validate()
    if (validationError) {
      setFormError(validationError)
      return
    }
    try {
      clearDialogError()
      setFormError(null)
      setSaving(true)
      if (editing) {
        await updateDecisionTool(editing.id, buildPayload())
      } else {
        await createDecisionTool(buildPayload())
      }
      onSaved()
      onClose()
    } catch (err) {
      setDialogError(err)
    } finally {
      setSaving(false)
    }
  }

  const openTypeViewer = (id: string, role: 'input' | 'output') => {
    const dataType = dataTypeList.find((d) => d.id === id)
    if (!dataType) return
    setViewingType({
      type: dataType,
      title: t(
        role === 'input'
          ? 'decisionTools.inputDataTypeView'
          : 'decisionTools.outputDataTypeView',
      ),
    })
  }

  const renderDataTypeSelector = (role: 'input' | 'output') => {
    const value =
      role === 'input' ? form.input_data_type_id : form.output_data_type_id
    const label =
      role === 'input'
        ? t('decisionTools.inputDataType')
        : t('decisionTools.outputDataType')
    return (
      <Stack direction="row" spacing={1} alignItems="center" width="100%">
        <TextField
          select
          label={label}
          value={value}
          onChange={(e) =>
            setForm((f) => ({
              ...f,
              [role === 'input' ? 'input_data_type_id' : 'output_data_type_id']:
                e.target.value,
            }))
          }
          fullWidth
          margin="normal"
          helperText={t('decisionTools.dataTypeHint')}
        >
          <MenuItem value="">{t('decisionTools.noDataType')}</MenuItem>
          {dataTypeList.map((d) => (
            <MenuItem key={d.id} value={d.id}>
              {d.name} ({d.slug})
            </MenuItem>
          ))}
        </TextField>
        <Tooltip title={t('decisionTools.viewDataType')}>
          <span>
            <IconButton
              size="small"
              disabled={!value}
              onClick={() => openTypeViewer(value, role)}
              aria-label={t('decisionTools.viewDataType')}
            >
              <VisibilityIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Stack>
    )
  }

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>
        {editing ? t('decisionTools.editTool') : t('decisionTools.addTool')}
      </DialogTitle>
      <DialogContent>
        {dialogError != null && (
          <PermissionDeniedAlert
            error={dialogError}
            fallbackMessage={t('app.error')}
          />
        )}
        {formError && (
          <Alert severity="warning" sx={{ mt: 1 }}>
            {formError}
          </Alert>
        )}
        {/* Readiness pre-validation: enabling requires both data types —
            explain inline instead of failing with a raw 422 on save. */}
        {readinessBlocked && (
          <Alert severity="warning" sx={{ mt: 1 }}>
            {t('decisionTools.validation.readinessRequiresTypes')}
          </Alert>
        )}

        {/* Configured-model gate */}
        {statusLoading ? (
          <Box display="flex" alignItems="center" gap={1} mt={2}>
            <CircularProgress size={18} />
            <Typography variant="body2">{t('app.loading')}</Typography>
          </Box>
        ) : statusError ? (
          <Alert severity="error" sx={{ mt: 2 }}>
            {statusError}
          </Alert>
        ) : !systemOneConfigured ? (
          <Alert
            severity="warning"
            sx={{ mt: 2 }}
            action={
              <Button
                color="inherit"
                size="small"
                component="a"
                href="/system/system-one"
                startIcon={<OpenInNewIcon />}
              >
                {t('decisionTools.openConfig')}
              </Button>
            }
          >
            {t('decisionTools.notConfigured')}
          </Alert>
        ) : (
          <Alert severity="info" sx={{ mt: 2 }}>
            {t('decisionTools.configuredHint', {
              model: statusInfo?.model ?? '',
              provider: statusInfo?.provider_type ?? '',
            })}
          </Alert>
        )}

        <TextField
          label={t('decisionTools.name')}
          value={form.name}
          disabled={!!editing}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          fullWidth
          margin="normal"
          required
          helperText={t('decisionTools.nameHint')}
        />
        <TextField
          label={t('decisionTools.purpose')}
          value={form.purpose}
          onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))}
          fullWidth
          margin="normal"
          required
          multiline
          minRows={2}
          helperText={t('decisionTools.purposeHint')}
        />

        {/* Input / output data type selectors (with read-only viewers) */}
        {renderDataTypeSelector('input')}
        {renderDataTypeSelector('output')}

        {/* AI-assisted draft generation */}
        <Box mt={1}>
          <Button
            startIcon={
              generating ? <CircularProgress size={16} /> : <AutoFixHighIcon />
            }
            onClick={() => void handleGenerate()}
            disabled={generating || !systemOneConfigured}
          >
            {t('decisionTools.generateWithAi')}
          </Button>
        </Box>

        {/* Questions builder — optional: auto-derived from the output data
            type when no manual questions are authored (override wins). */}
        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle1" fontWeight={600}>
          {t('decisionTools.questionsTitle')}
        </Typography>
        {form.questions.length === 0 && (
          <Alert severity="info" sx={{ mt: 1 }}>
            {t('decisionTools.questionsAutoGenerated')}
          </Alert>
        )}
        {form.questions.map((q, idx) => (
          <DecisionToolQuestionEditor
            key={idx}
            question={q}
            onChange={(next) =>
              setQuestions(form.questions.map((x, i) => (i === idx ? next : x)))
            }
            onRemove={() =>
              setQuestions(form.questions.filter((_, i) => i !== idx))
            }
          />
        ))}
        <Button
          startIcon={<AddIcon />}
          onClick={() => setQuestions([...form.questions, EMPTY_QUESTION()])}
          sx={{ mt: 1 }}
        >
          {t('decisionTools.addQuestion')}
        </Button>

        {/* Guided state preset mapper — ADVANCED: state is auto-generated
            from the input data type by default; advanced mapping optional. */}
        <Divider sx={{ my: 2 }} />
        <Accordion
          expanded={advancedOpen}
          onChange={(_, next) => setAdvancedOpen(next)}
        >
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Stack direction="row" spacing={1} alignItems="center">
              <Typography variant="subtitle1" fontWeight={600}>
                {t('decisionTools.statePreset')}
              </Typography>
              <Chip size="small" label={t('decisionTools.advanced')} />
            </Stack>
          </AccordionSummary>
          <AccordionDetails>
        <Typography variant="caption" color="text.secondary">
          {t('decisionTools.statePresetHint')}
        </Typography>
        {!inputDataType ? (
          <Alert severity="info" sx={{ mt: 1 }}>
            {t('decisionTools.selectInputTypeFirst')}
          </Alert>
        ) : (
          <>
            <Alert severity="info" sx={{ mt: 1 }}>
              {t('decisionTools.stateInjectionHelp')}
            </Alert>
            {/* AUTO-MATCH: placeholders equal to an input property resolve
                silently — the user is asked NOTHING about them. */}
            {Object.keys(matched).length > 0 && (
              <Stack direction="row" spacing={1} alignItems="center" mt={1} flexWrap="wrap">
                {Object.entries(matched).map(([key, field]) => (
                  <Chip
                    key={key}
                    size="small"
                    color="success"
                    variant="outlined"
                    label={`${key} → ${field}`}
                  />
                ))}
                <Typography variant="caption" color="text.secondary">
                  {t('decisionTools.autoMatchedHint')}
                </Typography>
              </Stack>
            )}
            {/* UNMATCHED placeholders: one mapper row each — the user must
                map the key to an input property. */}
            {unmatched.map((key) => {
              const row = form.state_preset.find((m) => m.state_key.trim() === key)
              const value = row?.key ?? ''
              return (
                <Stack key={key} direction="row" spacing={1} alignItems="center" mt={1}>
                  <Typography variant="body2" sx={{ minWidth: 220 }}>
                    {t('decisionTools.mapPlaceholder', { key })}
                  </Typography>
                  <TextField
                    size="small"
                    select
                    label={t('decisionTools.dataKey')}
                    value={value}
                    fullWidth
                    onChange={(e) =>
                      setForm((f) => {
                        const existing = f.state_preset.find(
                          (m) => m.state_key.trim() === key,
                        )
                        return {
                          ...f,
                          state_preset: existing
                            ? f.state_preset.map((m) =>
                                m.state_key.trim() === key
                                  ? { ...m, key: e.target.value }
                                  : m,
                              )
                            : [
                                ...f.state_preset,
                                { state_key: key, key: e.target.value },
                              ],
                        }
                      })
                    }
                  >
                    {inputFieldNames.map((name) => (
                      <MenuItem key={name} value={name}>
                        {name}
                      </MenuItem>
                    ))}
                  </TextField>
                </Stack>
              )
            })}
            {/* Explicit rows with an editable state key (loaded from the
                tool, AI-drafted, or added manually). */}
            {form.state_preset.map((m, idx) => (
              <Stack key={idx} direction="row" spacing={1} alignItems="center" mt={1}>
                <TextField
                  size="small"
                  label={t('decisionTools.stateKey')}
                  value={m.state_key}
                  sx={{ width: 180 }}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      state_preset: f.state_preset.map((x, i) =>
                        i === idx ? { ...x, state_key: e.target.value } : x,
                      ),
                    }))
                  }
                />
                <TextField
                  size="small"
                  select
                  label={t('decisionTools.dataKey')}
                  value={m.key}
                  fullWidth
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      state_preset: f.state_preset.map((x, i) =>
                        i === idx ? { ...x, key: e.target.value } : x,
                      ),
                    }))
                  }
                >
                  {inputFieldNames.map((name) => (
                    <MenuItem key={name} value={name}>
                      {name}
                    </MenuItem>
                  ))}
                </TextField>
                <Tooltip title={t('app.delete')}>
                  <IconButton
                    size="small"
                    onClick={() =>
                      setForm((f) => ({
                        ...f,
                        state_preset: f.state_preset.filter((_, i) => i !== idx),
                      }))
                    }
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
            ))}
            <Button
              size="small"
              startIcon={<AddIcon />}
              sx={{ mt: 1 }}
              onClick={() =>
                setForm((f) => ({
                  ...f,
                  state_preset: [...f.state_preset, { state_key: '', key: '' }],
                }))
              }
            >
              {t('decisionTools.addStateMapping')}
            </Button>
          </>
        )}
          </AccordionDetails>
        </Accordion>

        {/* Thresholds + flags */}
        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle1" fontWeight={600}>
          {t('decisionTools.thresholds')}
        </Typography>
        <Stack direction="row" spacing={2} mt={1} flexWrap="wrap">
          <TextField
            label={t('decisionTools.actThreshold')}
            type="number"
            inputProps={{ min: 0, max: 1, step: 0.05 }}
            value={form.act_threshold}
            sx={{ width: 180 }}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                act_threshold: Number(e.target.value),
              }))
            }
          />
          <TextField
            label={t('decisionTools.confirmThreshold')}
            type="number"
            inputProps={{ min: 0, max: 1, step: 0.05 }}
            value={form.confirm_threshold}
            sx={{ width: 200 }}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                confirm_threshold: Number(e.target.value),
              }))
            }
          />
          <TextField
            select
            label={t('decisionTools.modelSelection')}
            value={form.decision_model_availability_id}
            sx={{ minWidth: 260 }}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                decision_model_availability_id: e.target.value,
              }))
            }
            helperText={t('decisionTools.modelSelectionHint')}
          >
            {/* Placeholder: never render a silently blank select (create
                mode / legacy tools without an availability selection). */}
            <MenuItem value="">{t('decisionTools.modelNone')}</MenuItem>
            {enabledModels.map((m) => (
              <MenuItem key={m.availability_id} value={m.availability_id}>
                {m.model_name} — {m.provider_display_name}
              </MenuItem>
            ))}
            {/* FIX-20261014-004500: a stored selection that is no longer in
                the enabled list (vendor cascade / manual disable) must be
                visible as a disabled, clearly-hinted option instead of the
                select silently rendering empty. Validation still blocks the
                save (modelUnavailable) so the user must re-select. */}
            {form.decision_model_availability_id &&
              !enabledModels.some(
                (m) => m.availability_id === form.decision_model_availability_id,
              ) && (
                <MenuItem
                  value={form.decision_model_availability_id}
                  disabled
                >
                  {editing?.model_name || form.decision_model_availability_id}
                  {editing?.provider_display_name
                    ? ` — ${editing.provider_display_name}`
                    : ''}
                  {' — '}
                  {t('decisionTools.modelUnavailableOption')}
                </MenuItem>
              )}
          </TextField>
          <TextField
            select
            label={t('decisionTools.status')}
            value={form.status}
            sx={{ width: 150 }}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                status: e.target.value as DecisionToolStatus,
              }))
            }
          >
            <MenuItem value="draft">draft</MenuItem>
            <MenuItem value="active">active</MenuItem>
            <MenuItem value="disabled">disabled</MenuItem>
          </TextField>
          <FormControlLabel
            control={
              <Switch
                checked={form.enabled}
                onChange={(e) =>
                  setForm((f) => ({ ...f, enabled: e.target.checked }))
                }
              />
            }
            label={t('decisionTools.enabled')}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {t('decisionTools.thresholdsHint')}
        </Typography>

        {/* Generated description preview */}
        <Divider sx={{ my: 2 }} />
        <Typography variant="subtitle1" fontWeight={600}>
          {t('decisionTools.generatedDescription')}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {t('decisionTools.generatedDescriptionHint')}
        </Typography>
        <Paper variant="outlined" sx={{ p: 1.5, mt: 1, whiteSpace: 'pre-wrap' }}>
          <Typography variant="body2">{descriptionPreview}</Typography>
        </Paper>
        <Chip
          size="small"
          sx={{ mt: 1 }}
          label={`decision____${form.name || '…'}`}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('app.cancel')}</Button>
        <Button
          variant="contained"
          onClick={() => void handleSave()}
          disabled={
            saving ||
            readinessBlocked ||
            (statusInfo != null && !systemOneConfigured)
          }
        >
          {saving ? <CircularProgress size={20} /> : t('app.save')}
        </Button>
      </DialogActions>

      <DataTypeViewDialog
        dataType={viewingType?.type ?? null}
        title={viewingType?.title ?? ''}
        onClose={() => setViewingType(null)}
      />
    </Dialog>
  )
}

// Keep the summary type referenced for API typing parity (round-2 contract).
export type { AgentDataTypeSummary }
