# OAuth Auto-Discovery Implementation - Test Guide

## ✅ Implementation Summary

### Backend Changes
1. **Database Schema** (`backend/app/db/models/mcp_hub.py`)
   - ✅ Added `oauth_config: Mapped[dict | None]` JSON field to McpServer model

2. **API Schemas** (`backend/app/schemas/mcp_hub.py`)
   - ✅ Added `oauth_config` to McpServerUpdate and McpServerRead

3. **OAuth Endpoints** (`backend/app/api/v1/mcp_hub.py`)
   - ✅ `GET /mcp/servers/{server_id}/oauth/authorize` - Returns authorization URL
   - ✅ `GET /mcp/oauth/callback` - Exchanges code for tokens, auto-creates session

4. **Database Migration**
   - ✅ Created `abc123456789_add_oauth_config_to_mcp_servers.py`

### Frontend Changes
1. **OAuth Callback Page** (`frontend/src/pages/OAuthCallback.tsx`)
   - ✅ Calls backend `/mcp/oauth/callback` endpoint
   - ✅ Sends success/error message to parent window
   - ✅ Auto-closes popup

2. **Session Manager** (`frontend/src/pages/mcp/McpSessionManager.tsx`)
   - ✅ Simplified OAuth UI - single "Authenticate with OAuth" button
   - ✅ Removed all manual OAuth configuration fields
   - ✅ Refreshes session list after successful OAuth

3. **i18n** (`frontend/src/i18n/locales/en.json`)
   - ✅ Added OAuth instruction text
   - ✅ Added OAuth note about server-managed config

## 🧪 Manual Test Steps

### Prerequisites
- Backend running on `http://localhost:8000`
- Frontend running on `http://localhost:5173`
- Database migrations applied
- Admin/user account with MCP server management permissions

### Test 1: Verify Database Schema
```bash
cd backend
# Check if oauth_config column exists
python -c "from app.db.models.mcp_hub import McpServer; print('oauth_config' in [c.key for c in McpServer.__table__.columns])"
# Expected: True
```

### Test 2: Create MCP Server with OAuth Config

**Via API (Postman/curl):**
```bash
curl -X POST http://localhost:8000/api/v1/mcp/servers \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub MCP Server",
    "slug": "github-mcp",
    "base_url": "https://github-mcp.example.com",
    "oauth_config": {
      "authorization_url": "https://github.com/login/oauth/authorize",
      "token_url": "https://github.com/login/oauth/access_token",
      "client_id": "your-github-client-id",
      "client_secret": "your-github-client-secret",
      "scope": "read:user repo",
      "redirect_uri": "http://localhost:5173/oauth/callback"
    }
  }'
```

**Expected Response:**
```json
{
  "id": "uuid-here",
  "name": "GitHub MCP Server",
  "slug": "github-mcp",
  "base_url": "https://github-mcp.example.com",
  "oauth_config": {
    "authorization_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "client_id": "your-github-client-id",
    "client_secret": "your-github-client-secret",
    "scope": "read:user repo",
    "redirect_uri": "http://localhost:5173/oauth/callback"
  },
  "status": "active",
  ...
}
```

### Test 3: Get OAuth Authorization URL

```bash
curl -X GET "http://localhost:8000/api/v1/mcp/servers/{server-id}/oauth/authorize" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected Response:**
```json
{
  "authorization_url": "https://github.com/login/oauth/authorize?client_id=...&redirect_uri=...&response_type=code&state=..."
}
```

### Test 4: UI OAuth Flow

1. **Navigate to MCP Hub:**
   - Go to `http://localhost:5173/mcp`
   - Click on the server you configured with OAuth

2. **Click "Manage Sessions"**

3. **Click "Add Session"**
   - Select Auth Type: `oauth2`
   - Should see simplified UI with just:
     - Instructions text
     - "Authenticate with OAuth" button
     - Note about server-managed config

4. **Click "Authenticate with OAuth"**
   - Popup window should open
   - Should redirect to OAuth provider (e.g., GitHub)
   - Grant permissions
   - Popup should close automatically
   - Session list should refresh with new OAuth session

5. **Verify Session Created:**
   - Should see new session in list
   - Name: "OAuth Session - [timestamp]"
   - Auth Type: `oauth2`
   - Description: "Auto-created via OAuth flow"

### Test 5: Error Handling

**Test missing OAuth config:**
```bash
# Create server WITHOUT oauth_config
curl -X POST http://localhost:8000/api/v1/mcp/servers \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "No OAuth Server",
    "slug": "no-oauth",
    "base_url": "https://example.com"
  }'

# Try to get OAuth URL
curl -X GET "http://localhost:8000/api/v1/mcp/servers/{server-id}/oauth/authorize" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Expected:** HTTP 400 with error message about missing OAuth configuration

## 🔍 Verification Checklist

- [ ] Database migration applied successfully
- [ ] `oauth_config` field exists in `mcp_servers` table
- [ ] Can create MCP server with OAuth config
- [ ] Can retrieve OAuth config via API
- [ ] OAuth authorization URL endpoint works
- [ ] OAuth callback endpoint exists
- [ ] Frontend shows simplified OAuth UI
- [ ] "Authenticate with OAuth" button appears for oauth2 auth type
- [ ] No compilation/linting errors in frontend
- [ ] No Python import errors in backend

## 🎯 Key Features Implemented

1. **Server-Side OAuth Configuration**
   - Admins configure OAuth once per MCP server
   - Users don't need to know OAuth endpoints

2. **Auto-Session Creation**
   - Backend automatically creates session after successful OAuth
   - No manual session creation needed

3. **Secure Token Storage**
   - Tokens encrypted with AES-256 via CredentialVault
   - Stored in `encrypted_credentials` field

4. **Simplified User Experience**
   - Single button click to authenticate
   - Popup handles entire OAuth flow
   - Automatic session refresh

5. **State Management**
   - Secure state tokens prevent CSRF
   - State stored in-memory (production: Redis)

## 📝 OAuth Config Format

```json
{
  "authorization_url": "https://provider.com/oauth/authorize",
  "token_url": "https://provider.com/oauth/token",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret",
  "scope": "space-separated scopes",
  "redirect_uri": "http://localhost:5173/oauth/callback"
}
```

## 🚀 Next Steps

1. **Production Deployment:**
   - Replace `_mcp_oauth_states` dict with Redis
   - Add OAuth config validation
   - Add OAuth token refresh logic

2. **Enhanced Features:**
   - OAuth discovery from `.well-known` endpoints
   - Multiple OAuth providers per server
   - OAuth token expiration handling

3. **Testing:**
   - Add unit tests for OAuth endpoints
   - Add E2E tests for OAuth flow
   - Test with real OAuth providers (GitHub, Google, etc.)
