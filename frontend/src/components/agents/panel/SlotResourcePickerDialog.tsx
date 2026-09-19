import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { ResourcePickerDialog } from './ResourcePickerDialog'
import { getSlotPickerConfig } from './slotPickerConfigs'
import type { UseAgentDraftCompositionResult } from '../../../hooks/useAgentDraftComposition'
import type { AgentEquipmentSlotId, PanelDialogRequest } from '../../../types'

interface SlotResourcePickerDialogProps {
  /** Slot whose "Assign existing" action opened the picker (null = closed). */
  slotId: AgentEquipmentSlotId | null
  draftApi: UseAgentDraftCompositionResult
  /**
   * Overrides the equipped-ids pre-selection — set after an inline create so
   * the created resource is pre-selected in the refreshed list.
   */
  presetIds: string[] | null
  onClose: () => void
  /** Opens the slot's create-new flow in the shared dialog host. */
  onCreateNew: (request: PanelDialogRequest) => void
}

/**
 * Binds the generic ResourcePickerDialog to one equipment slot through its
 * SlotPickerConfig: runs the slot's list query (shared cache key with the
 * slot cards), maps rows, derives the pre-selection from the draft (or the
 * inline-create preset), and applies confirmed selections to the draft.
 * Draft mutations are draft-only — nothing is persisted until panel Save.
 */
export function SlotResourcePickerDialog({
  slotId,
  draftApi,
  presetIds,
  onClose,
  onCreateNew,
}: SlotResourcePickerDialogProps) {
  const { t } = useTranslation()
  const config = slotId ? getSlotPickerConfig(slotId) : null
  const open = config != null

  // Shares the slot cards' react-query cache — no duplicate network traffic,
  // and shared-dialog invalidations refresh the open picker's list.
  const query = useQuery({
    queryKey: config?.queryKey ?? ['agents', 'panel-picker', 'idle'],
    queryFn: config ? config.queryFn : async () => null,
    enabled: open,
  })

  const items = useMemo(
    () => (query.data != null && config ? config.toItems(query.data) : []),
    [query.data, config],
  )

  // Equipped ids: the change baseline; pre-selection only when no inline
  // create preset is pending.
  const equippedIds = useMemo(
    () => (config ? config.getSelectedIds(draftApi.draft, items) : []),
    [config, draftApi.draft, items],
  )
  const initialSelectedIds = useMemo(
    () => presetIds ?? equippedIds,
    [presetIds, equippedIds],
  )

  if (!config) return null

  const handleConfirm = (ids: string[]) => {
    config.apply(draftApi, ids, items)
    onClose()
  }

  return (
    <ResourcePickerDialog
      open={open}
      title={t('agents.panel.picker.title', { resource: t(config.labelKey) })}
      items={items}
      loading={query.isLoading}
      error={query.error}
      selectionMode={config.multi ? 'multi' : 'single'}
      initialSelectedIds={initialSelectedIds}
      baselineIds={equippedIds}
      onClose={onClose}
      onConfirm={handleConfirm}
      onCreateNew={() => onCreateNew(config.createRequest)}
    />
  )
}
