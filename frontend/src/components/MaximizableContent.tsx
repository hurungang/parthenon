import React, { useState } from 'react'
import { Box, Dialog, DialogTitle, IconButton } from '@mui/material'
import OpenInFullIcon from '@mui/icons-material/OpenInFull'
import CloseIcon from '@mui/icons-material/Close'

interface MaximizableContentProps {
  /** The rendered content to display inline and in the maximize dialog. */
  children: React.ReactNode
  /** Optional title displayed in the maximize dialog header. */
  title?: string
}

/**
 * Wraps any content area with a maximize button that opens the same content
 * in a full-view MUI Dialog. Acts as a pure layout/decorator — does not
 * alter how content is rendered.
 */
export function MaximizableContent({ children, title }: MaximizableContentProps) {
  const [isMaximized, setIsMaximized] = useState(false)

  const handleOpen = () => setIsMaximized(true)
  const handleClose = () => setIsMaximized(false)

  return (
    <>
      <Box
        sx={{
          position: 'relative',
          // Reserve space for the hover-revealed maximize button so content
          // never sits under it (the button used to overlap text).
          pr: 4.5,
          '&:hover .maximize-content-btn, &:focus-within .maximize-content-btn': {
            opacity: 1,
          },
        }}
      >
        {/* Inline content */}
        {children}

        {/* Maximize button — hidden until the bubble is hovered or focused
            so it never covers the content. */}
        <IconButton
          className="maximize-content-btn"
          onClick={handleOpen}
          size="small"
          aria-label={title ? `Maximize: ${title}` : 'Maximize content'}
          sx={{
            position: 'absolute',
            top: 4,
            right: 4,
            bgcolor: 'rgba(255, 255, 255, 0.85)',
            boxShadow: 1,
            opacity: 0,
            transition: 'opacity 0.15s ease',
            '&:hover': { bgcolor: 'rgba(255, 255, 255, 0.95)' },
          }}
        >
          <OpenInFullIcon fontSize="small" />
        </IconButton>
      </Box>

      {/* Full-view dialog */}
      <Dialog
        open={isMaximized}
        onClose={handleClose}
        fullWidth
        maxWidth={false}
        PaperProps={{
          sx: {
            height: '95vh',
            maxHeight: '95vh',
            m: 1,
          },
        }}
      >
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1, pr: 6 }}>
          {title && (
            <Box component="span" sx={{ flex: 1 }}>
              {title}
            </Box>
          )}
          <IconButton
            onClick={handleClose}
            size="small"
            aria-label="Close maximized view"
            sx={{ position: 'absolute', top: 8, right: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>

        <Box sx={{ flex: 1, overflow: 'auto', px: 3, py: 2 }}>
          {children}
        </Box>
      </Dialog>
    </>
  )
}
