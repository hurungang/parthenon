import '@testing-library/jest-dom'
import { configure } from '@testing-library/react'

// Increase async timeout to 5s so first-render initialization in jsdom doesn't
// cause false failures (React + MUI warmup on first test in each file).
configure({ asyncUtilTimeout: 5000 })
