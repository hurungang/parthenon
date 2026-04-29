import type { Shadows } from '@mui/material/styles'

const sm = '0 1px 2px 0 rgb(0 0 0 / 0.05)'
const md =
  '0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1)'
const lg =
  '0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1)'

export const shadows: Shadows = [
  'none', // 0
  sm,     // 1
  md,     // 2
  lg, lg, lg, lg, lg, lg, lg, lg, lg, lg, // 3–12
  lg, lg, lg, lg, lg, lg, lg, lg, lg, lg, // 13–22
  lg, lg,                                  // 23–24
]
