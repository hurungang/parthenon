import React from 'react'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  List,
  ListItem,
  ListItemText,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import type { AgentPlan } from '../../types'
import TopologyDiagramRenderer from './TopologyDiagramRenderer'

// ── Helpers ───────────────────────────────────────────────────────────────────

function getStepTypeChipColor(
  type: string
): 'primary' | 'secondary' | 'success' | 'default' {
  switch (type) {
    case 'sop_invocation':
      return 'primary'
    case 'skill_invocation':
      return 'secondary'
    case 'tool_call':
      return 'success'
    default:
      return 'default'
  }
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface Props {
  open: boolean
  onClose: () => void
  plan: AgentPlan | null
  agentTypeName: string
}

// ── Component ─────────────────────────────────────────────────────────────────

const PlanPreviewModal: React.FC<Props> = ({ open, onClose, plan, agentTypeName }) => {
  const { t } = useTranslation()

  const isFailed =
    !plan ||
    plan.generation_status === 'failed' ||
    plan.generation_status === 'pending'

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="xl"
      fullWidth
      aria-labelledby="plan-preview-dialog-title"
      PaperProps={{
        sx: {
          width: { xs: '100%', sm: '90%', lg: '95%' },
        },
      }}
    >
      <DialogTitle id="plan-preview-dialog-title">
        {t('agents.plan.previewTitle', { agentTypeName })}
      </DialogTitle>

      <DialogContent dividers>
        {isFailed ? (
          /* ── Failed / Pending state ─────────────────────────────────── */
          <Alert severity="warning">
            <Typography variant="subtitle2" gutterBottom>
              {t('agents.plan.generationFailed')}
            </Typography>
            {plan?.generation_error && (
              <Typography variant="body2">
                {plan.generation_error}
              </Typography>
            )}
          </Alert>
        ) : (
          <>
            {/* ── Implementation Steps ──────────────────────────────────── */}
            <Typography variant="h6" gutterBottom>
              {t('agents.plan.steps')}
            </Typography>

            {plan!.plan_steps.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                {t('agents.plan.noSteps')}
              </Typography>
            ) : (
              <List dense disablePadding>
                {[...plan!.plan_steps]
                  .sort((a, b) => a.order - b.order)
                  .map((step) => (
                    <ListItem
                      key={step.order}
                      alignItems="flex-start"
                      disableGutters
                      sx={{ py: 0.5 }}
                    >
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography
                              variant="caption"
                              sx={{
                                minWidth: 22,
                                fontWeight: 700,
                                color: 'text.secondary',
                              }}
                            >
                              {step.order}.
                            </Typography>
                            <Chip
                              label={t(`agents.plan.stepTypes.${step.type}`)}
                              size="small"
                              color={getStepTypeChipColor(step.type)}
                              variant="outlined"
                              sx={{ fontSize: 10, height: 20 }}
                            />
                            <Typography variant="body2" fontWeight={500}>
                              {step.name}
                            </Typography>
                          </Box>
                        }
                        secondary={
                          step.description ? (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ ml: 4, display: 'block' }}
                            >
                              {step.description}
                            </Typography>
                          ) : undefined
                        }
                      />
                    </ListItem>
                  ))}
              </List>
            )}

            {/* ── Topology Diagram ──────────────────────────────────────── */}
            {(plan!.topology_nodes.length > 0 || plan!.topology_edges.length > 0) && (
              <>
                <Divider sx={{ my: 2 }} />
                <Typography variant="h6" gutterBottom>
                  {t('agents.plan.topology')}
                </Typography>
                <TopologyDiagramRenderer
                  nodes={plan!.topology_nodes}
                  edges={plan!.topology_edges}
                />
              </>
            )}
          </>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} variant="outlined">
          {t('agents.plan.close')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export { PlanPreviewModal }
export default PlanPreviewModal
