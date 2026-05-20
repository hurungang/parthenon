# Notification Integration

## Overview
Notification Integration enables Parthenon agents, SOPs, and platform workflows to deliver timely, actionable messages to users and teams across multiple external channels. Platform administrators configure the available channels and recipient groups; agents and SOPs address notifications by recipient group slug, and the platform resolves delivery across all channels assigned to that group. Every notification attempt is logged for audit.

## Who Uses It
- **Platform Administrators**: Configure notification channels and recipient groups; monitor delivery logs
- **SOP Authors**: Define notification steps within agent workflows, targeting groups by slug
- **Agent Runtime**: Executes SOPs and triggers notifications via the `send_notification` tool
- **Support / Operations Teams**: Receive actionable alerts and updates through their preferred channels

## Notification Channels

Four channel types are supported. Each channel is configured independently with its own credentials and settings.

| Channel Type | Description |
|---|---|
| **SMTP Email** | Delivers via an SMTP relay (supports STARTTLS and SMTPS) |
| **Email API** | Delivers via an external email API provider (e.g., SendGrid, Mailgun) |
| **Webhook** | HTTP POST to a configured endpoint; supports HMAC signing for verification |
| **Instant Messenger** | Delivers to Microsoft Teams or Slack using their respective webhook/connector formats |

Secret credentials (passwords, API keys, signing secrets) for each channel are stored encrypted at rest and decrypted only at the moment of dispatch.

## Recipient Groups

A recipient group is a named, addressable audience that can be assigned one or more notification channels.

- Groups have a **display name** and a unique **slug** (auto-generated from the name)
- Agents and SOP instructions target a group by **slug** — the platform resolves all assigned channels and delivers to each
- One group may use multiple channels simultaneously (e.g., email + Slack)
- One channel may be shared across multiple groups

Administrators manage groups through the **Recipient Groups** admin page. The page displays a slug reminder for SOP authors: the `send_notification` and `get_recipient_group` tools use the group slug as their parameter, not the display name.

## Agent and SOP Notification

Agents and SOPs trigger notifications by calling the `send_notification` tool with:
- **Recipient group slug** — identifies the target audience
- **Message content** — the notification body to deliver

The platform records the source of each notification (`AGENT`, `SOP`, or `MANUAL`) alongside the session or SOP identifiers, providing a full audit trail from the instruction to the delivery attempt.

## Admin Management

Administrators manage the notification system through three dedicated admin pages:

- **Notification Channels** — Create, edit, and delete channel configurations; test-send to verify credentials
- **Recipient Groups** — Create, edit, and delete groups; assign/remove channels from a group; view channel count per group
- **Notification Log** — Browse all delivery attempts with filtering by status, date, and group; click any row for full delivery detail

## Delivery Audit

Every channel delivery attempt is recorded as an immutable log entry with:
- Source type and identifier (SOP, agent session, or manual trigger)
- Recipient group and channel used
- Delivery status: `DELIVERED` or `FAILED`
- Error detail on failure
- Timestamp of request and delivery

Partial failures (one channel fails, others succeed) are recorded individually — a group notification never silently drops a channel.

## Acceptance Criteria
- Admin can create, edit, and delete notification channels for all four channel types
- Admin can configure channel-specific credentials (encrypted at rest); credentials are never exposed in API responses
- Admin can create, edit, and delete recipient groups; each group can be assigned one or more channels
- Admins can perform a test send from any channel's edit view
- SOP authors can reference recipient groups by slug in SOP instructions
- Agents can trigger notifications by calling the `send_notification` tool with a group slug
- Notifications are delivered to all channels assigned to the target group; a failure on one channel does not block others
- Every delivery attempt is logged with source, status, and error detail
- Delivery log is filterable and accessible from the admin UI

## Out of Scope
- In-app (UI) notification banners or popups for end users
- SMS or voice call channels
- End-user self-service notification preferences
- Custom message templates or branding
- Bulk marketing or promotional messaging
