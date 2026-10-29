import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link,
  List,
  ListItem,
  ListItemText,
  TextField,
  Typography,
} from '@mui/material'
import SendIcon from '@mui/icons-material/Send'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'

// ── Types ──────────────────────────────────────────────────────────────────────

export interface OptimizedPlanStep {
  order?: number
  type?: string
  name?: string
  description?: string | null
  python_source?: string | null
  scriptable?: boolean
}

export interface FeedbackComment {
  created_at: string
  raw_feedback: string
  summary: string
}

export interface OptimizedPlanView {
  id: string
  agent_type_id: string
  agent_plan_id: string
  status: 'generating' | 'ready' | 'failed' | 'needs_feedback' | 'retired'
  fully_scripted: boolean
  error: string | null
  steps: OptimizedPlanStep[]
  steps_count: number
  scripts_authored: number
  feedback_comments: FeedbackComment[]
  generated_at: string | null
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface AgentOptimizedPlanTabProps {
  agentTypeId: string
  onError: (error: unknown) => void
  /** Opens the script view dialog for the clicked step's script. */
  onViewScript: (step: OptimizedPlanStep) => void
}

// ── Component ──────────────────────────────────────────────────────────────────

/**
 * "Optimized Plan" tab: shows the current optimized workflow composition
 * (steps + "View script" links), the plan status, and a feedback input whose
 * (LLM-summarized) comments are accumulated as memory for the next
 * regeneration.
 */
export function AgentOptimizedPlanTab({
  agentTypeId,
  onError,
  onViewScript,
}: AgentOptimizedPlanTabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [feedback, setFeedback] = useState('')

  const optimizedPlanKey = ['agents', 'types', agentTypeId, 'optimized-plan']

  const {
    data: plan,
    isLoading,
  } = useQuery<OptimizedPlanView>({
    queryKey: optimizedPlanKey,
    queryFn: async () => {
      const { data } = await apiClient.get<OptimizedPlanView>(
        `/agents/types/${agentTypeId}/optimized-plan`,
      )
      return data
    },
    enabled: !!agentTypeId,
    retry: false,
  })

  const feedbackMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/agents/types/${agentTypeId}/optimize-plan/feedback`, {
        feedback,
      })
    },
    onSuccess: async () => {
      setFeedback('')
      await queryClient.invalidateQueries({ queryKey: optimizedPlanKey })
    },
    onError: (error) => onError(error),
  })

  // Retire plan: MARKS the optimized plan `retired` (kept for reference) so
  // the next Run Agent flow finds no `ready` plan and offers the opt-in
  // optimization dialog again. Invalidate the WHOLE agent-type query scope
  // (optimized plan + base plan + cached run-gate state) so the Run Agent
  // launch dialog immediately re-evaluates and shows the opt-in dialog.
  const retireMutation = useMutation({
    mutationFn: async () => {
      await apiClient.post(`/agents/types/${agentTypeId}/optimized-plan/retire`)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['agents', 'types', agentTypeId],
        refetchType: 'all',
      })
      await queryClient.invalidateQueries({ queryKey: ['scripts'] })
    },
    onError: (error) => onError(error),
  })

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" pt={2}>
        <CircularProgress size={24} />
      </Box>
    )
  }

  // 404 (no optimized plan yet — e.g. after retiring) or any other fetch
  // failure → empty state with a hint that the next run offers optimization.
  if (!plan) {
    return (
      <Box>
        <Typography variant="body2" color="text.secondary" data-testid="optimized-plan-absent">
          {t('agents.optimizedPlan.noPlan')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {t('agents.optimizedPlan.absentHint')}
        </Typography>
      </Box>
    )
  }

  const isScriptStep = (step: OptimizedPlanStep): boolean =>
    Boolean(step.python_source || step.scriptable)

  return (
    <Box>
      {/* Status + execution semantics */}
      <Box display="flex" gap={1} alignItems="center" flexWrap="wrap" mb={1}>
        <Typography variant="caption" color="text.secondary">
          {t('agents.optimizedPlan.status')}
        </Typography>
        <Chip
          data-testid="optimized-plan-status"
          label={plan.status}
          size="small"
          color={
            plan.status === 'ready'
              ? 'success'
              : plan.status === 'failed'
                ? 'error'
                : plan.status === 'needs_feedback'
                  ? 'warning'
                  : 'info'
          }
        />
        <Chip
          label={
            plan.fully_scripted
              ? t('agents.optimizedPlan.fullyScripted')
              : t('agents.optimizedPlan.toolMode')
          }
          size="small"
          variant="outlined"
          color={plan.fully_scripted ? 'primary' : 'default'}
        />
        <Box sx={{ flexGrow: 1 }} />
        <Button
          variant="outlined"
          size="small"
          onClick={() => {
            if (!plan || plan.status === 'retired') {
              return
            }
            retireMutation.mutate()
          }}
          disabled={retireMutation.isPending || !plan || plan.status === 'retired'}
          data-testid="retire-optimized-plan"
        >
          {t('agents.optimizedPlan.retire')}
        </Button>
      </Box>
      {retireMutation.isSuccess && (
        <Alert severity="success" sx={{ mb: 1 }} data-testid="retire-success">
          {t('agents.optimizedPlan.retiredHint')}
        </Alert>
      )}
      {plan && plan.status === 'retired' && (
        <Alert severity="info" sx={{ mb: 1 }} data-testid="nothing-to-retire">
          {t('agents.optimizedPlan.nothingToRetire', 'Nothing to retire')}
        </Alert>
      )}

      {(plan.status === 'failed' || plan.status === 'needs_feedback') &&
        plan.error && (
          <Alert severity={plan.status === 'failed' ? 'error' : 'warning'} sx={{ mb: 2 }}>
            {plan.error}
          </Alert>
        )}
      {plan.status === 'needs_feedback' && (
        <Alert severity="info" sx={{ mb: 2 }} data-testid="needs-feedback-prompt">
          {t('agents.optimizedPlan.needsFeedbackPrompt')}
        </Alert>
      )}

      {/* Composition steps */}
      <Typography variant="subtitle2" gutterBottom>
        {t('agents.optimizedPlan.stepsTitle')}
      </Typography>
      {!plan.steps || plan.steps.length === 0 ? (
        <Typography variant="body2" color="text.secondary" mb={2}>
          {t('agents.optimizedPlan.noSteps')}
        </Typography>
      ) : (
        <List dense disablePadding sx={{ mb: 2 }}>
          {plan.steps.map((step, index) => (
            <ListItem
              key={index}
              disableGutters
              data-testid={`optimized-plan-step-${index}`}
              secondaryAction={
                isScriptStep(step) ? (
                  <Link
                    component="button"
                    variant="body2"
                    underline="hover"
                    data-testid={`view-script-link-${index}`}
                    onClick={() => onViewScript(step)}
                  >
                    {t('agents.optimizedPlan.viewScript')}
                  </Link>
                ) : null
              }
            >
              <ListItemText
                primary={step.name ?? `${t('agents.optimizedPlan.stepFallback')} ${index + 1}`}
                secondary={step.description ?? undefined}
              />
            </ListItem>
          ))}
        </List>
      )}

      <Divider sx={{ my: 2 }} />

      {/* Feedback loop (memory for the next regeneration) */}
      <Typography variant="subtitle2" gutterBottom>
        {t('agents.optimizedPlan.feedbackTitle')}
      </Typography>
      {(plan.feedback_comments ?? []).length > 0 && (
        <List dense disablePadding sx={{ mb: 1 }}>
          {plan.feedback_comments.map((comment, index) => (
            <ListItem key={index} disableGutters>
              <ListItemText
                primary={comment.summary}
                secondary={new Date(comment.created_at).toLocaleString()}
              />
            </ListItem>
          ))}
        </List>
      )}
      <TextField
        fullWidth
        multiline
        minRows={2}
        size="small"
        value={feedback}
        onChange={(e) => setFeedback(e.target.value)}
        placeholder={t('agents.optimizedPlan.feedbackPlaceholder')}
        data-testid="optimized-plan-feedback-input"
        sx={{ mb: 1 }}
      />
      {feedbackMutation.isSuccess && (
        <Alert severity="success" sx={{ mb: 1 }}>
          {t('agents.optimizedPlan.feedbackSaved')}
        </Alert>
      )}
      <Button
        variant="outlined"
        size="small"
        startIcon={<SendIcon />}
        disabled={!feedback.trim() || feedbackMutation.isPending}
        onClick={() => feedbackMutation.mutate()}
        data-testid="optimized-plan-feedback-submit"
      >
        {t('agents.optimizedPlan.feedbackSubmit')}
      </Button>
    </Box>
  )
}
