import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  TablePagination,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import SearchIcon from '@mui/icons-material/Search'
import PermissionDeniedAlert from '../../permissions/PermissionDeniedAlert'
import { useDialogErrorHandler } from '../../../hooks/useDialogErrorHandler'
import { usePagination } from '../../../hooks/usePagination'
import type { AgentDataType } from '../../../types'

/** Search debounce: typing filters the already-fetched list, not the server. */
const SEARCH_DEBOUNCE_MS = 250

/**
 * One selectable row of the resource picker: primary label + meaningful
 * sublabel, plus the raw Agent Data Type entry for the data-type slots so the
 * input slot can compose the typed input schema from the picked row.
 */
export interface ResourcePickerItem {
  id: string
  label: string
  sublabel: string | null
  /** Present for data-type rows only (registry entry with typed fields). */
  dataType?: AgentDataType
}

/** Single slots replace one draft value; multi slots reconcile add/remove. */
export type ResourcePickerSelectionMode = 'single' | 'multi'

interface ResourcePickerDialogProps {
  open: boolean
  title: string
  items: ResourcePickerItem[]
  loading: boolean
  /** Backing list query error — degrades gracefully inside the dialog (403). */
  error: unknown
  selectionMode: ResourcePickerSelectionMode
  /**
   * Ids pre-selected on open — the equipped ids at open time, or the created
   * resource id(s) after an inline create.
   */
  initialSelectedIds: string[]
  /**
   * Baseline for change detection (Assign disabled while identical). Defaults
   * to `initialSelectedIds`; the slot wrapper passes the EQUIPPED ids so an
   * inline-create preset counts as a valid pending change.
   */
  baselineIds?: string[]
  onClose: () => void
  /** Confirmed selection: single yields 0–1 ids, multi the reconciled set. */
  onConfirm: (ids: string[]) => void
  /** Opens the slot's create-new flow in the shared dialog host. */
  onCreateNew?: () => void
}

/**
 * Generic searchable + paginated resource selection dialog for the Agent
 * Management Panel equipment slots ("Assign existing"). Client-side search
 * (debounced) and client-side pagination run over the full fetched list, so
 * the picker scales with data growth without new server endpoints. Selection
 * follows the slot: single mode replaces one value, multi mode toggles
 * checkboxes and reconciles add/remove on confirm. Follows the Dialog Error
 * Handling Standard: errors render through PermissionDeniedAlert first in
 * DialogContent and are cleared on open/close.
 */
export function ResourcePickerDialog({
  open,
  title,
  items,
  loading,
  error,
  selectionMode,
  initialSelectedIds,
  baselineIds,
  onClose,
  onConfirm,
  onCreateNew,
}: ResourcePickerDialogProps) {
  const { t } = useTranslation()
  const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()

  // Change detection is always against the equipped state.
  const baseline = baselineIds ?? initialSelectedIds

  // Search state: controlled input + debounced committed value.
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')

  // Client-side pagination over the filtered list.
  const pag = usePagination({ initialRowsPerPage: 10, rowsPerPageOptions: [10, 25, 50] })

  // Selection — a Set for multi semantics; single mode keeps at most one id.
  const [selected, setSelected] = useState<Set<string>>(() => new Set(initialSelectedIds))

  // Reset search + error state on open (clear on open per the standard).
  useEffect(() => {
    if (open) {
      setSearchInput('')
      setSearch('')
      clearDialogError()
    }
    // clearDialogError is a stable setState wrapper; excluding it intentionally.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Adopt the incoming pre-selection whenever it changes (open or an inline
  // create presetting the created resource).
  useEffect(() => {
    if (open) {
      setSelected(new Set(initialSelectedIds))
    }
  }, [open, initialSelectedIds])

  // Commit the search input debounced; reset to the first page on commit.
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [searchInput])
  useEffect(() => {
    pag.resetPage()
    // pag.resetPage is a stable useCallback; reset pagination per search term.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (item) =>
        item.label.toLowerCase().includes(q) || (item.sublabel ?? '').toLowerCase().includes(q),
    )
  }, [items, search])

  // Clamp the page when the filtered list shrinks below the current page.
  const pageCount = Math.max(1, Math.ceil(filtered.length / pag.rowsPerPage))
  const safePage = Math.min(pag.page, pageCount - 1)
  const pageRows = filtered.slice(safePage * pag.rowsPerPage, (safePage + 1) * pag.rowsPerPage)

  const hasChange = useMemo(() => {
    if (selectionMode === 'single') {
      const current = selected.size > 0 ? [...selected][0] : null
      return current !== (baseline[0] ?? null)
    }
    if (selected.size !== baseline.length) return true
    const initial = new Set(baseline)
    for (const id of selected) {
      if (!initial.has(id)) return true
    }
    return false
  }, [selected, baseline, selectionMode])

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (selectionMode === 'single') return new Set([id])
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  /** Standard close: bubble up, then clear the dialog error state. */
  const handleClose = () => {
    onClose()
    clearDialogError()
  }

  const handleAssign = () => {
    try {
      clearDialogError()
      onConfirm([...selected])
    } catch (err) {
      setDialogError(err)
    }
  }

  const degraded = error != null

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="sm" fullWidth>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers>
        {/* Dialog Error Handling Standard: errors first in DialogContent. */}
        {(dialogError ?? error) != null && (
          <PermissionDeniedAlert
            error={dialogError ?? error}
            fallbackMessage={t('app.error')}
          />
        )}
        <TextField
          size="small"
          fullWidth
          placeholder={t('agents.panel.picker.searchPlaceholder')}
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <SearchIcon fontSize="small" />
              </InputAdornment>
            ),
          }}
        />
        <Box sx={{ mt: 1, minHeight: 200, maxHeight: 360, overflowY: 'auto' }}>
          {loading ? (
            <Box display="flex" justifyContent="center" py={4}>
              <CircularProgress size={28} />
            </Box>
          ) : degraded ? null : pageRows.length === 0 ? (
            <Typography variant="body2" color="text.secondary" py={4} textAlign="center">
              {t('agents.panel.picker.noMatch')}
            </Typography>
          ) : (
            <List dense disablePadding>
              {pageRows.map((item) => {
                const isSelected = selected.has(item.id)
                return (
                  <ListItemButton
                    key={item.id}
                    dense
                    selected={isSelected}
                    onClick={() => toggle(item.id)}
                  >
                    {selectionMode === 'multi' && (
                      <Checkbox
                        edge="start"
                        checked={isSelected}
                        tabIndex={-1}
                        disableRipple
                        inputProps={{ 'aria-label': item.label }}
                      />
                    )}
                    <ListItemText
                      disableTypography
                      primary={
                        <Box sx={{ minWidth: 0 }}>
                          <Tooltip title={item.label}>
                            <Typography variant="body2" noWrap sx={{ minWidth: 0 }}>
                              {item.label}
                            </Typography>
                          </Tooltip>
                          {item.sublabel && (
                            <Tooltip title={item.sublabel}>
                              <Typography
                                variant="caption"
                                color="text.secondary"
                                noWrap
                                sx={{ display: 'block', minWidth: 0 }}
                              >
                                {item.sublabel}
                              </Typography>
                            </Tooltip>
                          )}
                        </Box>
                      }
                    />
                  </ListItemButton>
                )
              })}
            </List>
          )}
        </Box>
        {!loading && !degraded && (
          <TablePagination
            component="div"
            count={filtered.length}
            page={safePage}
            onPageChange={pag.onPageChange}
            rowsPerPage={pag.rowsPerPage}
            onRowsPerPageChange={pag.onRowsPerPageChange}
            rowsPerPageOptions={pag.rowsPerPageOptions}
            labelRowsPerPage={t('app.rowsPerPage')}
          />
        )}
      </DialogContent>
      <DialogActions>
        {onCreateNew && (
          <Button onClick={onCreateNew} startIcon={<AddIcon />}>
            {t('agents.panel.createNew')}
          </Button>
        )}
        <Box sx={{ flex: 1 }} />
        <Button onClick={handleClose}>{t('app.cancel')}</Button>
        <Button
          variant="contained"
          disabled={!hasChange || degraded}
          onClick={handleAssign}
        >
          {t('agents.panel.picker.assign')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
