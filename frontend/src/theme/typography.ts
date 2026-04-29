import type { ThemeOptions } from '@mui/material/styles'

type TypographyOptions = NonNullable<ThemeOptions['typography']>

export const typography: TypographyOptions = {
  fontFamily: "'Inter', sans-serif",
  h1: {
    fontWeight: 700,
    letterSpacing: '-1px',
  },
  h2: {
    fontWeight: 700,
    letterSpacing: '-0.75px',
  },
  h3: {
    fontWeight: 700,
    letterSpacing: '-0.5px',
  },
  h4: {
    fontWeight: 700,
    letterSpacing: '-0.5px',
  },
  h5: {
    fontWeight: 600,
  },
  h6: {
    fontWeight: 600,
  },
  subtitle1: {
    fontWeight: 600,
    fontSize: '1rem',
  },
  subtitle2: {
    fontWeight: 600,
    fontSize: '0.8125rem',
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
  },
  body1: {
    fontWeight: 400,
    fontSize: '0.875rem',
  },
  body2: {
    fontWeight: 400,
    fontSize: '0.8125rem',
  },
  button: {
    fontWeight: 500,
    fontSize: '0.875rem',
  },
}
