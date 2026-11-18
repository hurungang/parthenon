import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link,
  Tooltip,
  Typography,
} from '@mui/material'
import ForumIcon from '@mui/icons-material/Forum'
import HelpOutlineIcon from '@mui/icons-material/HelpOutline'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import apiClient from '../../api/apiClient'
import { ConversationDialog } from './ConversationDialog'
import { OptimizationHelpDialog } from './OptimizationHelpDialog'
import { PlanStepTree } from './PlanStepTree'
import {
  localizeOptimizationConversationReason,
  localizeOptimizerModelReason,
  useOptimizationGate,
} from '../../hooks/useOptimizationGate'
import { invalidateOptimizedPlanQueries } from '../../hooks/useOptimizationConversation'
import { isOptimizerModelReasonCode } from '../../utils/errorUtils'

// ── Types ──────────────────────────────────────────────────────────────────────

export interface OptimizedPlanStep {
  order?: number
  /** Optional parent step ``order`` — flat steps render as a tree when set. */
  parent_order?: number | null
  type?: string | null
  name?: string | null
  description?: string | null
  python_source?: string | null
  scriptable?: boolean
}

/**
 * `source` discriminates how a feedback entry was recorded:
 *   - `manual`            — submitted by an operator (missing ⇒ manual, for
 *                           entries written before the discriminator existed)
 *   - `execution_derived` — auto-recorded when a later execution fell back to
 *                           the model path because of this plan
 */
export interface FeedbackComment {
  created_at: string
  raw_feedback: string
  summary: string
  source?: 'manual' | 'execution_derived'
  source_execution_id?: string | null
  source_fallback_event_id?: string | null
}

export interface OptimizedPlanView {
  id: string
  agent_type_id: string
  agent_plan_id: string
  status:
    | 'generating'
    | 'ready'
    | 'failed'
    | 'needs_feedback'
    | 'requires_fix'
    | 'retired'
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
  /** Optional display name used by the Re-optimize dialog title. */
  agentTypeName?: string | null
  onError: (error: unknown) => void
  /** Opens the script view dialog for the clicked step's script. */
  onViewScript: (step: OptimizedPlanStep) => void
  /**
   * System Config shortcut for the optimizer-model blocked state. Injected by
   * the host so this tab stays usable without a Router context.
   */
  onOpenSystemConfig?: () => void
}

/** How long to keep polling after an optimization run is triggered. */
const OPTIMIZE_POLL_WINDOW_MS = 5 * 60_000
/** Poll cadence while a plan is generating / an optimization run is in flight. */
const PLAN_POLL_INTERVAL_MS = 5_000

// ── Component ──────────────────────────────────────────────────────────────────

/**
 * "Optimized Plan" tab: a compact optimizer entry (model + "Talk to optimizer"
 * chat + question-mark help) beside the plan itself. "Talk to optimizer" opens
 * an optimization-mode conversation on THIS agent type (a mode of the agent,
 * not a separate optimizer agent). The verbose requirement copy, the manual
 * feedback form and the pre-start confirmation dialog were removed — the help
 * icon explains what optimization does.
 *
 * A plan marked `requires_fix` (a later execution fell back to the model path
 * because of it) surfaces a concise alert that points at the conversation. The
 * tab refreshes itself after a re-optimization run OR a conversation turn,
 * without a reload. Steps render as a tree via `PlanStepTree`.
 */
export function AgentOptimizedPlanTab({
  agentTypeId,
  agentTypeName,
  onError,
  onViewScript,
  onOpenSystemConfig,
}: AgentOptimizedPlanTabProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [optimizationChatOpen, setOptimizationChatOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  // Deadline while an optimization run triggered from this tab is in flight —
  // polls the plan so the tab updates without a manual reload.
  const [pollUntil, setPollUntil] = useState<number | null>(null)
  // Plan shown when the current optimization run started. A re-optimization
  // keeps the old (ready) row visible until the new one is persisted, so
  // polling must not stop on the pre-trigger plan.
  const pollBaselinePlanIdRef = useRef<string | null>(null)

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
    refetchInterval: (query) => {
      const current = query.state.data
      if (current?.status === 'generating') return PLAN_POLL_INTERVAL_MS
      if (pollUntil !== null && Date.now() < pollUntil) return PLAN_POLL_INTERVAL_MS
      return false
    },
  })

  // The optimization-conversation entry (available for typed AND conversational
  // subjects — `can_optimize` stays the ONE-SHOT precondition and is not used
  // here).
  const { data: gate } = useOptimizationGate(agentTypeId)
  const conversationAvailable =
    gate === undefined ? true : gate.optimization_conversation_available !== false
  const conversationReasonCode = gate?.optimization_conversation_reason_code ?? null
  const permissionBlocked = conversationReasonCode === 'permission_denied'
  const conversationReason = localizeOptimizationConversationReason(
    t,
    conversationReasonCode,
    null,
  )
  const modelReason = isOptimizerModelReasonCode(
    conversationReasonCode ?? gate?.optimizer_model_reason_code,
  )
    ? localizeOptimizerModelReason(
        t,
        conversationReasonCode ?? gate?.optimizer_model_reason_code,
        null,
      )
    : null
  const optimizerModelLabel = gate?.optimizer_model_id ?? null
  const optimizerModelInherited = gate?.optimizer_model_source === 'authoring'

  // A fresh plan landed after a re-optimization — stop polling and refresh the
  // whole agent-type scope (the hosting agent dialog, its Sessions tab and any
  // script views), not just this tab.
  useEffect(() => {
    if (pollUntil === null || !plan) return
    if (plan.status === 'generating') return
    // Still the pre-trigger plan: keep waiting for the new row.
    if (plan.id === pollBaselinePlanIdRef.current) return
    setPollUntil(null)
    void invalidateOptimizedPlanQueries(queryClient, agentTypeId)
  }, [plan, pollUntil, queryClient, agentTypeId])

  /**
   * 7.5 — auto-refresh. While a conversation turn is in flight the plan is
   * polled on the existing bounded cadence; when the turn settles (reply, pause,
   * denial, live-test result) the whole agent-type scope is invalidated so a
   * plan authored in the chat appears here without a reload.
   */
  const handleOptimizationTurnStateChange = (inFlight: boolean) => {
    if (inFlight) {
      pollBaselinePlanIdRef.current = plan?.id ?? null
      setPollUntil(Date.now() + OPTIMIZE_POLL_WINDOW_MS)
    }
  }
  const handleOptimizationTurnSettled = () => {
    void invalidateOptimizedPlanQueries(queryClient, agentTypeId)
  }

  // Retire plan: MARKS the optimized plan `retired` (kept for reference) so
  // execution no longer prefers it. Invalidate the WHOLE agent-type query
  // scope (optimized plan + base plan + cached Optimize gate state) so every
  // surface re-evaluates immediately.
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

  // Only a missing permission disables the entry: a missing model / reference
  // run / plan must OPEN the conversation, which is where the operator learns
  // what is missing. Typed and conversational subjects are equally allowed.
  const canOpenOptimizationChat = !permissionBlocked

  /** The optimization-mode conversation on THIS agent type (mode of the agent). */
  const optimizationConversationDialog = optimizationChatOpen ? (
    <ConversationDialog
      open
      sessionId={null}
      agentTypeId={agentTypeId}
      agentTypeName={agentTypeName ?? t('agents.optimizedPlan.stepFallback')}
      onClose={() => setOptimizationChatOpen(false)}
      testIdPrefix="optimization-conversation-dialog"
      optimizationMode
      onOptimizationTurnStateChange={handleOptimizationTurnStateChange}
      onOptimizationTurnSettled={handleOptimizationTurnSettled}
    />
  ) : null

  /**
   * The conversational entry. Rendered in EVERY state — a missing plan is an
   * informational empty state, never a hidden/disabled entry, and conversational
   * agents get exactly the same action as typed ones.
   */
  const renderOptimizationEntry = () => (
    <Box
      data-testid="talk-to-optimizer-entry"
      sx={{
        display: 'flex',
        gap: 1,
        alignItems: 'center',
        flexWrap: 'wrap',
        mb: 2,
        pb: 2,
        borderBottom: 1,
        borderColor: 'divider',
      }}
    >
      <Typography variant="body2" color="text.secondary">
        {optimizerModelLabel ? (
          <>
            {t('agents.optimizedPlan.talkToOptimizerModelLabel')}{' '}
            <Typography component="span" variant="body2" fontWeight={600}>
              {optimizerModelLabel}
            </Typography>
            {optimizerModelInherited
              ? ` (${t('agents.optimizedPlan.talkToOptimizerModelInherited')})`
              : ''}
          </>
        ) : (
          <Typography component="span" variant="body2" color="warning.dark">
            {t('agents.optimizedPlan.talkToOptimizerModelMissing')}
          </Typography>
        )}
      </Typography>
      <Tooltip
        title={t('agents.optimizedPlan.helpTitle', {
          defaultValue: 'About optimization',
        })}
      >
        <IconButton
          size="small"
          onClick={() => setHelpOpen(true)}
          aria-label={t('agents.optimizedPlan.helpTitle', {
            defaultValue: 'About optimization',
          })}
          data-testid="optimization-help"
        >
          <HelpOutlineIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Box sx={{ flexGrow: 1 }} />
      <Button
        variant="contained"
        color="secondary"
        startIcon={<ForumIcon />}
        disabled={!canOpenOptimizationChat}
        onClick={() => setOptimizationChatOpen(true)}
        data-testid="talk-to-optimizer"
      >
        {t('agents.optimizedPlan.talkToOptimizer')}
      </Button>
      {permissionBlocked && (
        <Typography
          variant="caption"
          color="error.main"
          display="block"
          sx={{ width: '100%' }}
          data-testid="talk-to-optimizer-blocked"
        >
          {t('agents.optimizedPlan.talkToOptimizerPermission')}
        </Typography>
      )}
      {!permissionBlocked && !conversationAvailable && (
        <Box sx={{ width: '100%' }} data-testid="talk-to-optimizer-blocked">
          <Typography variant="caption" color="warning.dark" display="block">
            {conversationReason ??
              t('agents.optimizedPlan.talkToOptimizerBlocked', {
                reason: t('agents.optimizer.modelAlertTitle'),
              })}
          </Typography>
          {modelReason && onOpenSystemConfig && (
            <Link
              component="button"
              variant="caption"
              underline="hover"
              onClick={onOpenSystemConfig}
              data-testid="talk-to-optimizer-system-config"
            >
              {t('agents.optimizer.openSystemConfig')}
            </Link>
          )}
        </Box>
      )}
    </Box>
  )

  /**
   * THE PLAN SECTION (one of three shapes): loading spinner, "no plan yet"
   * informational empty state, or the plan itself.
   *
   * Deliberately a SECTION inside the single tab shell at the bottom of this
   * component — never its own `return`. A shape switch (e.g. the plan query
   * refetching after a conversation turn while a 404 has no cached data) must
   * NOT remount the optimization ConversationDialog: remounting drops the
   * in-progress session, closes its socket and forgets the just-created
   * conversation.
   */
  const renderPlanSection = () => {
    if (isLoading) {
      return (
        <Box display="flex" justifyContent="center" pt={2}>
          <CircularProgress size={24} />
        </Box>
      )
    }

    // 404 (no optimized plan yet — e.g. after retiring, or a conversational
    // agent that has never been optimized) → the conversation still opens; the
    // plan section explains there is nothing to optimize yet.
    if (!plan) {
      return (
        <>
          <Alert severity="info" data-testid="optimized-plan-absent">
            <Typography variant="subtitle2" fontWeight={700}>
              {t('agents.optimizedPlan.talkToOptimizerEmptyTitle')}
            </Typography>
            <Typography variant="body2">{t('agents.optimizedPlan.noPlan')}</Typography>
            <Typography variant="body2">{t('agents.optimizedPlan.talkToOptimizerEmptyBody')}</Typography>
            <Typography variant="caption" color="text.secondary" display="block" mt={0.5}>
              {t('agents.optimizedPlan.talkToOptimizerEmptyConversational')}
            </Typography>
            <Typography variant="body2" color="text.secondary" mt={1}>
              {t('agents.optimizedPlan.absentHint')}
            </Typography>
          </Alert>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {t('agents.optimizedPlan.talkToOptimizerPlanRefresh')}
          </Typography>
        </>
      )
    }

    return (
      <>
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
                : plan.status === 'failed' || plan.status === 'requires_fix'
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

        {/* requires_fix: a later execution fell back because of this plan */}
        {plan.status === 'requires_fix' && (
          <Alert severity="error" sx={{ mb: 2 }} data-testid="requires-fix-alert">
            <Typography variant="subtitle2" fontWeight={700}>
              {t('agents.optimizedPlan.requiresFixTitle')}
            </Typography>
            <Typography variant="body2" sx={{ mt: 0.5 }}>
              {t('agents.optimizedPlan.requiresFixReason')}
            </Typography>
            {canOpenOptimizationChat && (
              <Button
                size="small"
                variant="text"
                color="secondary"
                sx={{ mt: 0.5, px: 0 }}
                onClick={() => setOptimizationChatOpen(true)}
                data-testid="reoptimize-from-alert"
              >
                {t('agents.optimizer.title')}
              </Button>
            )}
          </Alert>
        )}

        {plan.status === 'failed' && plan.error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {plan.error}
          </Alert>
        )}
        {plan.status === 'needs_feedback' && (
          <Alert severity="warning" sx={{ mb: 2 }} data-testid="needs-feedback-prompt">
            <Typography variant="subtitle2" gutterBottom>
              {t('agents.optimizedPlan.needsInputTitle')}
            </Typography>
            {plan.error && (
              <Typography variant="body2" sx={{ mb: 1 }}>
                {plan.error}
              </Typography>
            )}
            {canOpenOptimizationChat && (
              <Button
                size="small"
                variant="text"
                color="secondary"
                sx={{ mt: 0.5, px: 0 }}
                onClick={() => setOptimizationChatOpen(true)}
                data-testid="continue-in-conversation"
              >
                {t('agents.optimizer.title')}
              </Button>
            )}
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
          <Box sx={{ mb: 2 }}>
            <PlanStepTree
              steps={plan.steps.map((step, index) => ({
                ...step,
                order: step.order ?? index + 1,
              }))}
              onViewScript={(step) => onViewScript(step)}
              testIdPrefix="optimized-plan"
            />
          </Box>
        )}
      </>
    )
  }

  return (
    <Box data-testid="optimized-plan-tab">
      {renderOptimizationEntry()}
      {renderPlanSection()}

      {/* Optimization help (what it does + how to interact) — replaces the
          interrupted pre-start confirmation dialog. */}
      <OptimizationHelpDialog open={helpOpen} onClose={() => setHelpOpen(false)} />

      {/* Optimization-mode conversation on THIS agent type. Mounted ONCE,
          outside the branch-specific plan content, so a plan refresh never
          remounts it and never drops the live session. */}
      {optimizationConversationDialog}
    </Box>
  )
}
