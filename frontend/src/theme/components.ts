import type { Components, Theme } from '@mui/material/styles'

export const components: Components<Theme> = {
  MuiCard: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: 12,
        boxShadow: theme.shadows[1],
        border: '1px solid #e2e8f0',
      }),
    },
  },
  MuiPaper: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: 12,
        boxShadow: theme.shadows[1],
      }),
    },
  },
  MuiButton: {
    styleOverrides: {
      root: {
        borderRadius: 8,
        textTransform: 'none',
        fontWeight: 500,
      },
    },
  },
  MuiChip: {
    styleOverrides: {
      root: {
        borderRadius: 12,
        fontWeight: 600,
        fontSize: 12,
      },
    },
  },
  MuiListItemButton: {
    styleOverrides: {
      root: ({ theme }) => ({
        borderRadius: 8,
        '&:hover': {
          backgroundColor: theme.palette.primary.light,
          color: theme.palette.primary.main,
        },
        '&.Mui-selected': {
          backgroundColor: theme.palette.primary.light,
          color: theme.palette.primary.main,
          '&:hover': {
            backgroundColor: theme.palette.primary.light,
            color: theme.palette.primary.main,
          },
        },
      }),
    },
  },
  MuiAppBar: {
    styleOverrides: {
      root: ({ theme }) => ({
        backgroundColor: theme.palette.background.paper,
        color: theme.palette.text.primary,
        boxShadow: 'none',
        borderBottom: '1px solid #e2e8f0',
      }),
    },
  },
  MuiDrawer: {
    styleOverrides: {
      paper: {
        borderRight: '1px solid #e2e8f0',
        boxShadow: 'none',
      },
    },
  },
  MuiAvatar: {
    styleOverrides: {
      root: ({ theme }) => ({
        backgroundColor: theme.palette.primary.main,
        fontWeight: 600,
      }),
    },
  },
  MuiTableCell: {
    styleOverrides: {
      head: {
        fontWeight: 600,
        fontSize: 13,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        borderBottom: '2px solid #e2e8f0',
      },
    },
  },
  MuiTableRow: {
    styleOverrides: {
      root: ({ theme }: { theme: Theme }) => ({
        '&.MuiTableRow-body:hover': {
          backgroundColor: theme.palette.background.default,
        },
      }),
    },
  },
}
