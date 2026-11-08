# OneCore AI API

All routes require a bearer token and an active organization context through X-Organization-ID (unless the request host resolves a tenant). Records are persisted in the configured application database and isolated by organization and owning user.

- GET /api/v1/ai/status — provider configuration and capability availability; no secrets are returned.
- GET /api/v1/ai/sessions — recent conversations owned by the signed-in user.
- GET /api/v1/ai/sessions/{id} — messages for an owned conversation.
- POST /api/v1/ai/chat — prompt, optional session_id, language, branch_id and task.
- GET /api/v1/ai/usage — token counters for the signed-in user.
- DELETE /api/v1/ai/sessions/{id} — owner-only conversation and message deletion.

The provider adapter expects an OpenAI-compatible chat-completions endpoint. Configure the primary provider using INTEGRATION_AI_ENABLED, AI_BASE_URL, AI_API_KEY and AI_MODEL. Optionally configure the fallback with INTEGRATION_AI_FALLBACK_ENABLED, AI_FALLBACK_BASE_URL, AI_FALLBACK_API_KEY and AI_FALLBACK_MODEL. Store API keys only in a managed secret store or protected deployment environment.

Chat history and token usage are stored in the shared SQL database. Prompt content is sent to the configured provider. Do not submit sensitive personal, clinical, payment-card or credential data unless the organization has approved the provider and lawful processing basis. The assistant is advisory; it cannot execute database queries, payments, messages or other business actions.

This API does not yet implement binary document/PDF/XLSX ingestion, voice, image generation/understanding, autonomous agents/tool calls, private model hosting, approval-executed actions, cost-based billing, automated retention or provider cost reconciliation. Capability flags report these as unavailable.
