import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'

import { createTheme } from '@mui/material/styles'
import { palette } from './palette'
import { typography } from './typography'
import { shadows } from './shadows'
import { components } from './components'

export const parthenon = createTheme({
  palette,
  typography,
  shadows,
  components,
})
