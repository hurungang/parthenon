# Module: notifications — Tech Spec

## Overview

The notifications module provides a pluggable outbound notification system that agents and SOPs can invoke as part of their execution. Administrators configure notification channels (email via SMTP, Slack webhook, Microsoft Teams webhook, or generic HTTP webhook); each configured channel is registered as an MCP tool on the platform, making it directly callable by agents. The module also maintains an event history of all dispatched notifications and supports a test-send operation to validate channel configuration.

---

## Key Components

### Backend

| Component | Description |
|-----------|-------------|
| `NotificationDispatcher` | Service class that dispatches notifications to the appropriate channel implementation (SMTP, Slack, Teams, or generic webhook) based on the channel type; registers each active channel as an invocable MCP tool on the platform |
| `NotificationRouter` | FastAPI router providing full CRUD operations on notification channel configuration, a test-send endpoint to verify a channel is working, and an event history listing endpoint |
| `NotificationChannel` | SQLAlchemy model for a configured outbound notification destination; stores channel type, connection parameters (encrypted where sensitive), and enabled state |
| `NotificationEvent` | SQLAlchemy model recording a single dispatched notification; stores the target channel, payload summary, delivery status, and timestamp |

### Frontend

| Component | Description |
|-----------|-------------|
| `NotificationConfigPage` | Channel list with add and edit forms per channel type (email, Slack, Teams, webhook), test-send action per channel, and notification event history table |

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/notifications/channels` | List all configured notification channels |
| `POST` | `/api/v1/notifications/channels` | Create a notification channel |
| `PUT` | `/api/v1/notifications/channels/{channel_id}` | Update a channel configuration |
| `DELETE` | `/api/v1/notifications/channels/{channel_id}` | Delete a channel |
| `POST` | `/api/v1/notifications/channels/{channel_id}/test` | Send a test notification via the channel |
| `GET` | `/api/v1/notifications/events` | List notification dispatch events |

---

## Code Reference Map

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `NotificationDispatcher` | class | Dispatches notifications to configured channels; registers each channel as an MCP tool | `backend/app/services/notifications/dispatcher.py` |
| `NotificationRouter` | router | CRUD, test-send, and event history endpoints for notification channels | `backend/app/api/v1/notifications.py` |
| `NotificationChannel` | model | SQLAlchemy model for a configured outbound notification destination (type, config, enabled state) | `backend/app/db/models/notifications.py` |
| `NotificationEvent` | model | SQLAlchemy model recording a dispatched notification with channel, payload summary, and status | `backend/app/db/models/notifications.py` |
| `NotificationConfigPage` | component | Channel list, add/edit form per channel type, test-send, and event history table | `frontend/src/pages/notifications/NotificationConfigPage.tsx` |
