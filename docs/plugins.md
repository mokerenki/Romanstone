# Plugins, Nango, and n8n

This guide explains how a SynthAI plugin is made available to users and then exposed to the agent.

## Architecture

```text
plugin_registry row + Nango integration + n8n MCP workflow
                         |
Plugins grid <--- SynthAI API checks capability and connection status
                         |
User selects Connect -> Nango Connect UI -> provider OAuth consent
                         |
Nango stores and refreshes provider credentials
                         |
n8n workflow calls Nango Proxy using connection ID
                         |
MCP Server Trigger exposes the workflow as an agent tool
```

Credentials must stay in Nango. SynthAI stores only the opaque Nango connection ID, provider configuration key, n8n workflow ID, and MCP endpoint metadata. n8n must call the Nango proxy and must not contain Slack, Google, Notion, Salesforce, or other provider credentials.

## Plugin registry

The backend creates and seeds the `plugin_registry` PostgreSQL table at startup. Its source and initial rows are in [plugin_registry.py](../backend/app/services/plugin_registry.py).

| Field | Purpose |
| --- | --- |
| `id` | SynthAI's unique plugin ID, for example `google_calendar`. |
| `provider_key` | Nango integration ID; more than one plugin can share it, such as Calendar and Meet using `google`. |
| `display_name` | Name shown in the Plugins grid. |
| `description` | Card description. |
| `category` | `Communication`, `Productivity`, `CRM`, or `Finance`. |
| `icon` | Frontend icon key. |
| `feature_bullets` | String array rendered as the card capability tags. |
| `n8n_workflow_id` | Optional explicit n8n workflow ID. Use this when a provider name is not enough to identify a workflow. |
| `auth_status_source` | `nango`, `manual`, or `unsupported`. |

The Plugins API is `GET /api/integrations`. It merges registry data, n8n MCP capability, and the signed-in user's connection state. `GET /api/integrations/status` returns only per-user status.

## Add a Nango OAuth plugin

Example: adding HubSpot.

1. Register a single OAuth application in HubSpot's developer console.
2. In the Nango dashboard, create an integration with unique key `hubspot` and configure its client ID, client secret, requested scopes, and Nango's callback URL:

   ```text
   http://localhost:3003/oauth/callback
   ```

   Use the deployed Nango URL instead of `localhost` outside local development.
3. Add the provider mapping in [nango.py](../backend/app/services/nango.py):

   ```python
   NANGO_INTEGRATIONS["hubspot"] = "hubspot"
   ```

4. Add a `PluginRegistry` seed row in [plugin_registry.py](../backend/app/services/plugin_registry.py), with `auth_status_source="nango"` and `provider_key="hubspot"`.
5. Create and activate its n8n MCP workflow as described below.
6. Restart the backend. The registry row is inserted automatically if it does not exist already.

To modify an existing seeded row, run an explicit SQL `UPDATE`; seeds use `ON CONFLICT DO NOTHING` so they never overwrite live configuration.

## n8n workflow requirements

An n8n workflow makes a plugin agent-capable only when all these conditions are true:

1. It is active.
2. It contains an **MCP Server Trigger** node.
3. It matches the plugin either by its `n8n_workflow_id` field or by containing the provider key in its workflow name or n8n tag.
4. It calls the Nango proxy, never a provider with a copied provider token.

Recommended convention:

```text
Workflow name: SynthAI · hubspot · actions
n8n tag:       hubspot
```

For an HTTP Request node that calls the provider through Nango, configure:

```text
URL: {{ $env.NANGO_PROXY_URL + '/proxy/<provider-api-path>' }}
Authorization: Bearer {{ $env.NANGO_SECRET_KEY }}
Connection-Id: <the connected user's Nango connection ID>
Provider-Config-Key: hubspot
```

The required n8n environment values are set in `docker-compose.yml`:

```text
NANGO_PROXY_URL=http://nango-server:3003
NANGO_SECRET_KEY=<Nango environment secret key>
```

The MCP Server Trigger endpoint is what SynthAI discovers and registers as an agent tool. Keep its bearer authentication separate from Nango and from provider authorization.

## How the user Connect flow works

1. The card is enabled only when `auth_status_source` is `nango` and a matching n8n MCP workflow exists.
2. The frontend requests `GET /api/integrations/{plugin_id}/connect`.
3. SynthAI asks Nango for a short-lived Connect session tied to the current user and tenant.
4. The frontend calls `openConnectUI()` from Nango's official frontend SDK.
5. The user completes the provider's OAuth consent screen.
6. Nango returns `connectionId` and `providerConfigKey`.
7. The frontend posts those identifiers to SynthAI; no OAuth token passes through the browser app or is saved by SynthAI.
8. SynthAI saves the identifiers in the user's connection record and provisions/synchronizes the n8n MCP workflow.

## Unsupported or manual providers

Use `auth_status_source="unsupported"` for a visible card with a disabled **Coming soon** button. Sage and WhatsApp use this today.

- Sage needs a product-specific authentication investigation because auth differs between Sage products.
- WhatsApp needs Meta Business API and embedded-signup research.

Use `auth_status_source="manual"` only after adding a deliberately designed manual-credential flow. Do not reintroduce token entry for providers already supported by Nango OAuth.

## Current provider mapping

| Plugin | Nango integration key | Status |
| --- | --- | --- |
| Slack | `slack` | Nango OAuth once a matching n8n MCP workflow exists. |
| Google Calendar | `google` | Nango OAuth once a matching n8n MCP workflow exists. |
| Google Meet | `google` | Nango OAuth once a matching n8n MCP workflow exists. |
| Notion | `notion` | Nango OAuth once a matching n8n MCP workflow exists. |
| Salesforce | `salesforce` | Nango OAuth once a matching n8n MCP workflow exists. |
| Sage | — | Coming soon. |
| WhatsApp | — | Coming soon. |

## Troubleshooting

- Every OAuth card says **Coming soon**: create/activate a matching n8n workflow with an MCP Server Trigger and make sure `N8N_API_KEY` is configured.
- Connect UI cannot open: confirm `NANGO_SECRET_KEY`, `NANGO_PUBLIC_URL`, `NANGO_CONNECT_URL`, and `NANGO_ENCRYPTION_KEY` are configured; Nango's ports are `3003` and `3009` locally.
- Connection succeeds but the agent cannot use it: check that the matching n8n workflow is active, its MCP trigger is reachable, and the workflow calls the Nango proxy with the user's connection ID and provider key.
