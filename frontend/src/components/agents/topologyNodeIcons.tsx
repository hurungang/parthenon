import type { ComponentType, ReactElement } from 'react'
import AccountTree from '@mui/icons-material/AccountTree'
import Construction from '@mui/icons-material/Construction'
import Dns from '@mui/icons-material/Dns'
import Fingerprint from '@mui/icons-material/Fingerprint'
import Groups from '@mui/icons-material/Groups'
import Handyman from '@mui/icons-material/Handyman'
import Hub from '@mui/icons-material/Hub'
import Input from '@mui/icons-material/Input'
import ManageAccounts from '@mui/icons-material/ManageAccounts'
import Output from '@mui/icons-material/Output'
import Psychology from '@mui/icons-material/Psychology'
import SmartToy from '@mui/icons-material/SmartToy'
import type { SvgIconProps } from '@mui/material/SvgIcon'

/**
 * Entity-type icons for topology nodes (zoned agent panel): every node kind
 * carries a small leading icon so entity types are recognisable beyond the
 * colour map. MUI `SvgIcon`s render as nested `<svg>` elements inside the
 * parent topology SVG (valid SVG nesting).
 *
 * GEOMETRY CONTRACT (defect fix): a nested `<svg>` inside another `<svg>`
 * MUST carry explicit `width`/`height`/`x`/`y`/`viewBox` presentation
 * attributes — without them the nested viewport defaults to the FULL parent
 * SVG size (icons render at "original size" and overlap). MUI's root class
 * sizes icons via CSS (`width: 1em`), which overrides presentation
 * attributes, so the icon also gets an equivalent INLINE style (inline style
 * beats any class) and the `viewBox="0 0 24 24"` intrinsic box scales the
 * 24×24 icon paths down to the requested pixel size.
 */
export const NODE_TYPE_ICONS: Record<string, ComponentType<SvgIconProps>> = {
  agent: SmartToy,
  identity: Fingerprint,
  role: ManageAccounts,
  sop: AccountTree,
  skill: Construction,
  input_data_type: Input,
  output_data_type: Output,
  model: Psychology,
  tool: Handyman,
  mcp_server: Dns,
  agent_type: Groups,
  communication_hub: Hub,
}

interface TopologyNodeIconProps {
  /** Node type key (see `NODE_TYPE_ICONS`). */
  type: string
  /** Icon size in SVG units (square). */
  size: number
  /** Icon colour (defaults to `currentColor`). */
  color?: string
  /** Position of the nested icon SVG inside the parent SVG. */
  x: number
  y: number
  /** Value of the `data-node-icon` attribute (per-node test targeting). */
  testId?: string
}

/**
 * Renders one entity-type icon as a nested SVG inside the topology SVG, with
 * explicit pixel geometry (position `x`/`y`, size `width`/`height`, own
 * `viewBox`) so it never falls back to the parent SVG's viewport size and
 * always fits inside its node's layout box. Returns `null` for unknown node
 * types (no placeholder square is drawn).
 */
export function TopologyNodeIcon({ type, size, color, x, y, testId }: TopologyNodeIconProps): ReactElement | null {
  const Icon = NODE_TYPE_ICONS[type]
  if (!Icon) return null
  return (
    <Icon
      x={x}
      y={y}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      // Inline style wins over MUI's `width: 1em`/`height: 1em` root class —
      // the nested SVG is exactly `size` px regardless of inherited font-size.
      style={{
        fontSize: `${size}px`,
        width: `${size}px`,
        height: `${size}px`,
        ...(color ? { color } : {}),
      }}
      {...(testId ? { 'data-node-icon': testId } : {})}
    />
  )
}
