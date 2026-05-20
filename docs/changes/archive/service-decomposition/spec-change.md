# Service Decomposition — Specification Change

## Affected Spec Areas
- docs/master/architecture/: System architecture diagrams and service boundaries
- docs/master/deployment/: Deployment instructions for multi-service setup
- docs/master/operations/: Operations documentation for certificate management and service monitoring

 - docs/master/product/: Product spec for tool naming conventions, tool routing, and agent runtime behavior
 - docs/master/agent-runtime/: Agent runtime tool execution and tool name resolution logic

## New Capabilities
- Independent deployment and scaling of Control Center, Agent Runtime, and Communication Hub
- Certificate-based authentication (mTLS) for all service-to-service communication
- Centralized certificate authority and management in Control Center
- Strict enforcement of data access boundaries (no direct DB access outside Control Center)
- Test service authentication infrastructure enabling automated testing of service-to-service interactions

 - Unified `mcp_server____tool_name` (4-underscore) naming convention for all tools (system and MCP alike)
 - Central name resolver module for tool routing
 - Agent Runtime treats all tools uniformly; no distinction between system and MCP tools in agent execution code
 - Explicit invocation of `save_result` tool; runtime does not automatically call it

## Modified Capabilities
- All data access by Agent Runtime and Communication Hub now flows through Control Center APIs
- Service-to-service authentication now requires valid certificates issued by Control Center
- Control Center initiates calls to Agent Runtime and Communication Hub for execution and messaging
- Deployment and operations workflows updated for multi-service management
- Test suite now participates in the service ecosystem with certificate-based authentication

 - All tool names must follow the `server____tool` format (4 underscores). `system` is reserved for built-in tools (e.g., `system____save_result`). MCP server names cannot contain `____`.
 - Agent Runtime and Communication Hub must use a central resolver to route tool calls based on the unified naming convention. No agent-side distinction between system and MCP tools.
 - The runtime must not automatically call `save_result` at agent completion; agents must call it explicitly if required.

## Spec Update Instructions
- Update architecture diagrams in docs/master/architecture/ to show three-service decomposition and trust boundaries
- Revise deployment instructions in docs/master/deployment/ for multi-service orchestration, certificate bootstrapping, and mTLS configuration
- Update operations docs in docs/master/operations/ to cover certificate issuance, rotation, and audit logging
- Ensure all references to direct database access by Agent Runtime or Communication Hub are removed from master docs
- Add guidance for local development workflows involving multiple services

 - Update product spec in docs/master/product/ to document the unified tool naming convention, reserved `system` prefix, and MCP server name restrictions
 - Update agent runtime documentation to specify that all tools are handled uniformly and routed via the central resolver
 - Remove any documentation or code references to automatic invocation of `save_result` by the runtime; clarify that agents must call it explicitly