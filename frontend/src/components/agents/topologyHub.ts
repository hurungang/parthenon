import type { TopologyEdge, TopologyNode } from '../../types'

/** Fixed node id of the Communication Hub platform node in topology graphs. */
export const COMMUNICATION_HUB_NODE_ID = 'communication_hub'

/**
 * Idempotently appends the Communication Hub platform node and a dashed
 * agent↔hub edge to an existing node/edge set. Safe to call repeatedly with
 * server-generated plans or recomposed drafts — the hub is never duplicated.
 * Purely client-side: no runtime integration with the Communication Hub
 * service (the hub is a static platform node, consistent with the
 * three-service segregation rules).
 */
export function withCommunicationHub(
  nodes: TopologyNode[],
  edges: TopologyEdge[],
  hubLabel: string,
  edgeLabel?: string,
): { nodes: TopologyNode[]; edges: TopologyEdge[] } {
  if (nodes.some((node) => node.id === COMMUNICATION_HUB_NODE_ID)) {
    return { nodes, edges }
  }
  return {
    nodes: [
      ...nodes,
      { id: COMMUNICATION_HUB_NODE_ID, type: 'communication_hub', label: hubLabel },
    ],
    edges: [
      ...edges,
      {
        source: 'agent',
        target: COMMUNICATION_HUB_NODE_ID,
        style: 'dashed',
        ...(edgeLabel ? { label: edgeLabel } : {}),
      },
    ],
  }
}
