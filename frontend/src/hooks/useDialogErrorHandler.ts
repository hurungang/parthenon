import { useState } from 'react'

/**
 * Standard hook for managing dialog error state.
 * 
 * **Usage Pattern (Standard for all Dialogs):**
 * 
 * 1. Add the hook to your component:
 *    ```ts
 *    const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
 *    ```
 * 
 * 2. Wrap async operations in try-catch:
 *    ```ts
 *    const handleSave = async () => {
 *      try {
 *        clearDialogError()
 *        await mutation.mutateAsync(data)
 *        setDialogOpen(false)
 *      } catch (err) {
 *        setDialogError(err)
 *      }
 *    }
 *    ```
 * 
 * 3. Clear error when opening/closing dialog:
 *    ```ts
 *    const openDialog = () => {
 *      clearDialogError()
 *      setDialogOpen(true)
 *    }
 *    
 *    onClose={() => { setDialogOpen(false); clearDialogError() }}
 *    ```
 * 
 * 4. Display error in DialogContent:
 *    ```tsx
 *    <DialogContent>
 *      {dialogError && <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />}
 *      {/* rest of content *\/}
 *    </DialogContent>
 *    ```
 * 
 * @example
 * ```tsx
 * export function MyPage() {
 *   const [dialogOpen, setDialogOpen] = useState(false)
 *   const { dialogError, setDialogError, clearDialogError } = useDialogErrorHandler()
 *   
 *   const handleSave = async () => {
 *     try {
 *       clearDialogError()
 *       await apiClient.post('/my-endpoint', data)
 *       setDialogOpen(false)
 *     } catch (err) {
 *       setDialogError(err)
 *     }
 *   }
 *   
 *   return (
 *     <Dialog open={dialogOpen} onClose={() => { setDialogOpen(false); clearDialogError() }}>
 *       <DialogContent>
 *         {dialogError && <PermissionDeniedAlert error={dialogError} fallbackMessage={t('app.error')} />}
 *         {/* form fields *\/}
 *       </DialogContent>
 *     </Dialog>
 *   )
 * }
 * ```
 */
export function useDialogErrorHandler() {
  const [dialogError, setDialogError] = useState<unknown>(null)

  const clearDialogError = () => setDialogError(null)

  return {
    /** Current error state for the dialog */
    dialogError,
    /** Set error when operation fails */
    setDialogError,
    /** Clear error (call when opening dialog or before retry) */
    clearDialogError,
  }
}
