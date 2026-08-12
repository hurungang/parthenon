import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { useAgentTypes } from '../../hooks/useAgentTypes'
import { ConversationDialog } from '../../components/agents/ConversationDialog'

/**
 * Route wrapper for the conversation dialog.
 * Keeps the /chat route working while reusing the single dialog implementation.
 */
export function ChatPage() {
  const navigate = useNavigate()
  const { agentTypeId, sessionId } = useParams<{ agentTypeId?: string; sessionId?: string }>()
  const { data: agentTypes } = useAgentTypes()

  if (!agentTypeId) {
    return <Navigate to="/agents" replace />
  }

  const agentTypeName = agentTypes?.find((agentType) => agentType.id === agentTypeId)?.name ?? ''

  return (
    <ConversationDialog
      open
      sessionId={sessionId ?? null}
      agentTypeId={agentTypeId}
      agentTypeName={agentTypeName}
      initialFullscreen
      testIdPrefix="chat"
      onClose={() => {
        navigate('/agents', { state: { openDialogFor: agentTypeId } })
      }}
    />
  )
}
