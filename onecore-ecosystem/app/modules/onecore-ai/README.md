# OneCore AI

Master specification category 16.

## Implemented in this slice
- Authenticated organization-scoped AI gateway using configured OpenAI-compatible chat-completions providers.
- Primary and fallback provider routing; provider keys remain backend-only environment secrets.
- Persistent tenant-scoped conversations, message history and token usage in the shared SQL database.
- Chat tasks: general assistance, summarization, explanation, analysis, drafting and coding help.
- Language selection for English, Kiswahili, French, Arabic, Somali, Amharic, Hausa, Yoruba, Zulu and Portuguese prompts.
- Usage counters, audit events, owner-only conversation access and role-gated create/read/delete operations.
- Capability discovery so the UI does not advertise unsupported capabilities as active.

## Not yet implemented
PDF/binary file processing, XLSX upload analysis, speech-to-text/text-to-speech, image generation/understanding, database-connected agents/tool execution, workflow automation, predictive forecasting, private deployments, human-approval action execution, cost-based hybrid billing, retention schedules and provider-specific usage/cost reconciliation. These require separate provider adapters, storage/queue/approval workflows and operational validation. No generated action is executed by chat.

## Configuration
Set INTEGRATION_AI_ENABLED=true, AI_BASE_URL, AI_API_KEY and AI_MODEL. Optional fallback: INTEGRATION_AI_FALLBACK_ENABLED=true, AI_FALLBACK_BASE_URL, AI_FALLBACK_API_KEY and AI_FALLBACK_MODEL. Use the deployment secret manager for keys; never commit them.
