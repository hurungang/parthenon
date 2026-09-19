import { useQueryClient } from '@tanstack/react-query'
import { AgentRoleDialog } from '../AgentRoleDialog'
import { AgentIdentityDialog } from '../AgentIdentityDialog'
import { SkillEditor } from '../SkillEditor'
import { SopEditor } from '../SopEditor'
import { DataTypeFormDialog } from '../DataTypeFormDialog'
import { ModelConfigDialog } from '../ModelConfigDialog'
import type {
  AgentEquipmentSlotId,
  CreateAndAssignResult,
  PanelDialogRequest,
} from '../../../types'

/** Module dialog kinds handled by the host (agent create lives in the page). */
type ModuleDialogKind = Exclude<PanelDialogRequest['kind'], 'agent_create'>

/** Maps a dialog request kind to the equipment slot its created resource belongs to. */
const KIND_TO_SLOT: Record<ModuleDialogKind, AgentEquipmentSlotId> = {
  role: 'role',
  identity: 'identity',
  skill: 'skills',
  sop: 'sops',
  input_data_type: 'input_data_type',
  output_data_type: 'output_data_type',
  model_config: 'model',
}

interface SharedDialogHostProps {
  /** Which shared dialog to mount (null = none). Only one dialog at a time. */
  request: PanelDialogRequest | null
  onClose: () => void
  /**
   * Create-and-assign contract: invoked after a successful inline create with
   * the created resource (id + display label) and the target slot id, so the
   * caller can assign it into the draft.
   */
  onCreateAndAssign: (slotId: AgentEquipmentSlotId, result: CreateAndAssignResult) => void
}

/**
 * Single mount point for the extracted module dialogs inside the Agent
 * Management Panel. Each dialog is mounted exactly as its source page mounts
 * it (same props usage), so inline creation behaves identically to the source
 * module. The dialogs implement the Dialog Error Handling Standard themselves;
 * the host refreshes the relevant list caches after each successful save and
 * routes created resources into the create-and-assign callback.
 */
export function SharedDialogHost({ request, onClose, onCreateAndAssign }: SharedDialogHostProps) {
  const queryClient = useQueryClient()

  if (!request) return null

  const handleSaved = (kind: ModuleDialogKind, result?: CreateAndAssignResult) => {
    if (kind === 'role') {
      void queryClient.invalidateQueries({ queryKey: ['agents', 'roles'] })
    } else if (kind === 'identity') {
      void queryClient.invalidateQueries({ queryKey: ['agents', 'identities'] })
    } else if (kind === 'skill') {
      void queryClient.invalidateQueries({ queryKey: ['skills'] })
    } else if (kind === 'sop') {
      void queryClient.invalidateQueries({ queryKey: ['sops'] })
    } else if (kind === 'input_data_type' || kind === 'output_data_type') {
      void queryClient.invalidateQueries({ queryKey: ['data-types'] })
    } else if (kind === 'model_config') {
      void queryClient.invalidateQueries({ queryKey: ['agents', 'model-configs'] })
    }
    if (result) {
      onCreateAndAssign(KIND_TO_SLOT[kind], result)
    }
    onClose()
  }

  switch (request.kind) {
    case 'role':
      return (
        <AgentRoleDialog
          open
          editRole={null}
          mode="create"
          onClose={onClose}
          onSaved={async (result) => handleSaved('role', result)}
        />
      )
    case 'identity':
      return (
        <AgentIdentityDialog
          open
          onClose={onClose}
          onSaved={async (result) => handleSaved('identity', result)}
        />
      )
    case 'skill':
      return (
        <SkillEditor
          open
          skill={null}
          mode="create"
          onClose={onClose}
          onSaved={(result) => handleSaved('skill', result)}
        />
      )
    case 'sop':
      return (
        <SopEditor
          open
          sop={null}
          mode="create"
          onClose={onClose}
          onSaved={(result) => handleSaved('sop', result)}
        />
      )
    case 'input_data_type':
      return (
        <DataTypeFormDialog
          open
          editDataType={null}
          onClose={onClose}
          onSaved={async (result) => handleSaved('input_data_type', result)}
        />
      )
    case 'output_data_type':
      return (
        <DataTypeFormDialog
          open
          editDataType={null}
          onClose={onClose}
          onSaved={async (result) => handleSaved('output_data_type', result)}
        />
      )
    case 'model_config':
      return (
        <ModelConfigDialog
          open
          config={null}
          onClose={onClose}
          onSaved={(result) => handleSaved('model_config', result)}
        />
      )
    default:
      // agent_create is handled by the panel page itself (create dialog).
      return null
  }
}
