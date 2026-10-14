# Anthropic Claude API as a first-class provider (desktop app, Python FastAPI backend over HTTPS)

Method note: all pages fetched 2026-10-14 from platform.claude.com/docs (docs.anthropic.com 301-redirects there). None of the pages show a "last updated" date; the only dated statements are those quoted below (model retirement dates, beta header names with dates). Page-level "version" = API version header `2023-06-01`. Items not on a fetched page are marked UNVERIFIED.

## 1. Authentication, key format, cheap validation, workspaces

### Takeaway
Send `x-api-key` (legacy but supported) or `Authorization: Bearer`, plus `anthropic-version: 2023-06-01` and `content-type: application/json`, to `https://api.anthropic.com`. There is no dedicated "validate key" endpoint in the docs; `GET /v1/models?limit=1` is the cheapest documented authenticated call (inference, see below). Multi-workspace keys require an `anthropic-workspace-id` header.

### Cited Findings
- Base URL `https://api.anthropic.com`. Required headers: `anthropic-version` (e.g. `2023-06-01`), `content-type: application/json`; auth is `Authorization: Bearer <token>` unless `x-api-key` is set; `x-api-key` is "Legacy fallback ... still supported". — [API overview](https://platform.claude.com/docs/en/api/overview)
- SDKs send auth, version and content-type headers automatically; `anthropic-workspace-id` must be passed by you when the key needs it. — [API overview](https://platform.claude.com/docs/en/api/overview)
- Key format: static `sk-ant-api...` secret (example `sk-ant-api03-...`). Env var `ANTHROPIC_API_KEY` is picked up by SDKs. — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Key types: Personal key, Service account key, Workspace key (legacy). Identity-backed keys stop working when the user/service account is removed. — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Keys can be scoped to a single workspace (header optional) or multi-workspace (header `anthropic-workspace-id: wrkspc_...` required on every request). Missing header on an unscoped key gives 400 `invalid_request_error` ("anthropic-workspace-id is required when authenticating with an identity-linked API key..."); invalid ID gives 400; unknown/no-access workspace gives 404 `not_found_error`. — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Key expiration is chosen at creation (3h, 1d, 7d, 30d, custom, or Never; org policy may forbid Never); expired keys return 401 `authentication_error` and cannot be reactivated. — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Response headers on every call: `request-id`, `anthropic-organization-id`, `anthropic-workspace-id` (the workspace the key resolved to; absent if auth fails). — [API overview](https://platform.claude.com/docs/en/api/overview)
- Models API accepts optional `anthropic-workspace-id`; "A credential that belongs to a specific Workspace may omit it; if sent, it must match that Workspace." — [List Models](https://platform.claude.com/docs/en/api/models-list)
- Other documented auth modes (not needed for a desktop BYOK app): Workload Identity Federation (short-lived token via `POST /v1/oauth/token`), and App Attest for iOS/macOS apps calling the API directly (token expires after 1 hour, Messages API only). — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Docs recommend a backend proxy for browser-based apps (CORS not supported for ZDR orgs). — [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

### Inferences
- Cheap validation: call `GET /v1/models?limit=1`. It is authenticated, free of token spend, and returns 401 for bad/expired/revoked keys, 403 for permission problems, 400/404 for workspace header problems. The docs do not describe it as a validation endpoint, so treat as an inference. `POST /v1/messages/count_tokens` is a second no-cost option (token counting is free, but is rate limited).
- A 200 from /v1/models proves the key is valid but not that spend limits/billing allow inference (402 `billing_error`, 429 spend cap, 400 user-set spend limit appear only on Messages calls).
- For a user-supplied key, store `anthropic-organization-id`/`anthropic-workspace-id` response headers to show the user which workspace the key resolved to.

### Gaps
- No documented prefix distinction between personal/service/workspace keys beyond `sk-ant-api...` (UNVERIFIED whether other prefixes such as `sk-ant-oat`/admin keys exist for this API).
- Header precedence if both `x-api-key` and `Authorization` are sent is not documented.

## 2. Model discovery (Models API), current IDs, defaults, deprecations

### Takeaway
`GET /v1/models` returns id, display_name, created_at, lifecycle, line, max_input_tokens, max_tokens and a rich `capabilities` object, newest first. As of this fetch the current lineup is Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5; Docs say start with Opus 5.5 for most workloads. For an analysis-oriented desktop app, Sonnet 5.5 is the speed/intelligence default per the docs' own description; drive the choice from the API's `capabilities`, not hardcoded IDs.

### Cited Findings
- Endpoint `GET /v1/models`; query: `limit` (default 20, 1-1000), `after_id`, `before_id`, `lifecycle` (array of active|deprecated|retired, max 3; default returns active+deprecated). Response: `data[]`, `first_id`, `last_id`, `has_more`. "More recently released models are listed first." — [List Models](https://platform.claude.com/docs/en/api/models-list)
- ModelInfo fields: `type:"model"`, `id`, `display_name`, `created_at` (RFC 3339), `deprecated_at`, `retires_at`, `lifecycle` (active|deprecated|retired), `line` (haiku|sonnet|opus|fable|mythos or null; "do not infer a line from the id"), `max_input_tokens`, `max_tokens` (max value for request `max_tokens`), `capabilities`. — [List Models](https://platform.claude.com/docs/en/api/models-list)
- `capabilities` keys: batch, citations, code_execution, context_management, effort (low/medium/high/max/xhigh), image_input, pdf_input, server_tools (web_search, code_execution), structured_outputs, thinking (types.adaptive/enabled/disabled). — [List Models](https://platform.claude.com/docs/en/api/models-list)
- There is also a Retrieve model endpoint (reference page not fetched). UNVERIFIED shape; presumably `GET /v1/models/{model_id}` returning one ModelInfo.
- Current lineup (Claude API IDs; all pinned snapshots, also used as aliases):

| Model | API ID | Price in/out per MTok | Context | Max output | Default effort | Retirement commitment |
|---|---|---|---|---|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | $10 / $50 | 1M | 128K | high | not sooner than 2027-09-01 |
| Claude Opus 5.5 | `claude-opus-5-5` | $4 / $20 | 1M | 128K | medium | not sooner than 2027-09-22 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | $2 / $10 | 1M | 128K | high | not sooner than 2027-09-28 |
| Claude Haiku 5.5 | `claude-haiku-5-5` | from $0.10 / from $0.50 | 1M | 128K | medium | not sooner than 2027-10-07 |

  Knowledge cutoff for all four: Jun 2026. — [Models overview](https://platform.claude.com/docs/en/models/overview)
- "If you're unsure which model to use, start with Claude Opus 5.5 for most workloads. Use Claude Fable 5.1 for demanding reasoning and long-horizon agentic work." Sonnet 5.5 is described as "best combination of speed and intelligence"; Haiku 5.5 for classification/extraction/routing. — [Models overview](https://platform.claude.com/docs/en/models/overview)
- Legacy still-available: Fable 5, Opus 5, Opus 4.8/4.7/4.6/4.5, Sonnet 5, Sonnet 4.6, Haiku 4.5. — [Models overview](https://platform.claude.com/docs/en/models/overview)
- Every model ID is a pinned snapshot, "including the dateless IDs used from the 4.6 generation on"; for pre-4.6 models the alias (e.g. `claude-sonnet-4-5`) points to a dated ID. — [Models overview](https://platform.claude.com/docs/en/models/overview)
- Deprecations visible in the Messages reference: `claude-mythos-preview` EOL June 30, 2026 (migrate to claude-mythos-5); `claude-sonnet-4-5` / `claude-sonnet-4-5-20250929` EOL November 30, 2026 (migrate to claude-sonnet-5-5). — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- Tokenizer: Claude 4.7+ (incl. Fable/Mythos 5.x) produce ~30% more tokens for the same text than earlier models; recount with the target model. — [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- Mythos models are "available through trusted access programs" and Fable 5.x/Mythos 5.x are Covered Models requiring 30-day retention, so a BYOK key from an org with ZDR may be refused (400 `invalid_request_error`). — [Create a Message](https://platform.claude.com/docs/en/api/messages/create); [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)

### Inferences
- Model picker: list with default `lifecycle` filter, group by `line`, hide `deprecated` unless already selected, show `retires_at`, gate UI features (thinking toggle, effort, structured outputs, images/PDF) on `capabilities`, cap `max_tokens` at the model's `max_tokens`. Cache the list (TTL of hours) and let users pick; fall back to a bundled default (`claude-sonnet-5-5`) if the call fails.
- Default recommendation: Sonnet 5.5 for interactive analysis (cost $2/$10, 1M context); offer Haiku 5.5 for cheap routing/summaries and Opus 5.5/Fable 5.1 as "deep" modes.

### Gaps
- Retrieve-model endpoint response not fetched (UNVERIFIED).
- Full deprecation table (model-deprecations page) not fetched; only dates surfaced in the API reference are listed.
- Models page footers reference Mythos 5.1 specs; not detailed here (restricted access).

## 3. Messages API: request/response, system, max_tokens, sampling, stop reasons

### Takeaway
`POST /v1/messages` with `model`, `max_tokens`, `messages` (required) and optional `system`, `stop_sequences`, `stream`, `tools`, `tool_choice`, `thinking`, `output_config`, `metadata`, `service_tier`. On models released after Opus 4.6 (so all current 5.x models) `temperature`/`top_p`/`top_k` are effectively not settable, and prefill is rejected.

### Cited Findings
- `max_tokens` required, minimum 0 (0 = populate prompt cache without generating); `messages` max 100,000 per request; consecutive same-role turns are merged; there is no `system` role in messages, use top-level `system` (string or array of text blocks, `minLength: 1`). — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- `metadata.user_id` (maxLength 512) should be an opaque ID with no names/emails/phones. — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- `temperature` deprecated: "Models released after Claude Opus 4.6 do not support setting temperature. A value of 1.0 will be accepted ... all other values ... rejected with a 400". `top_p` accepted only if >= 0.99; `top_k` any value rejected on those models. — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- Prefill (trailing assistant message) returns 400 on Claude 4.6+ and Mythos Preview: "This model does not support assistant message prefill. The conversation must end with a user message." Use structured outputs / system instructions instead. — [Errors](https://platform.claude.com/docs/en/api/errors)
- `service_tier`: `auto` or `standard_only`. Request size cap 32 MB for Messages and Token Counting; exceeding gives 413 `request_too_large` (returned by Cloudflare on the direct API). — [API overview](https://platform.claude.com/docs/en/api/overview); [Errors](https://platform.claude.com/docs/en/api/errors)
- Response: `id`, `type:"message"`, `role:"assistant"`, `model`, `content[]` (text, thinking, redacted_thinking, tool_use, server_tool_use, and server tool result blocks), `stop_reason`, `stop_sequence`, `stop_details`, `usage`. — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- `usage`: `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `cache_creation{ephemeral_5m/1h_input_tokens}`, `output_tokens_details.thinking_tokens`, `server_tool_use`, `service_tier` (standard|priority|batch), `inference_geo`. Total input = input + cache_creation + cache_read. — [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- `stop_reason` values: `end_turn`, `max_tokens`, `stop_sequence`, `tool_use`, `pause_turn` (server-tool loop hit iteration limit, default 10; send assistant content back unchanged to continue), `refusal` (HTTP 200; `stop_details.category` in cyber|bio|frontier_llm|reasoning_extraction|general_harms), `model_context_window_exceeded`. In streaming it is null in `message_start`. — [Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons); [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- Empty `end_turn` responses (about 2-3 tokens) should not be retried unchanged; remove text blocks placed directly after `tool_result` blocks. — [Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- Do not set a large `max_tokens` without streaming or batches (idle connection drops); SDKs reject non-streaming requests expected to exceed 10 minutes. — [Errors](https://platform.claude.com/docs/en/api/errors)
- Minimal request:
```json
{"model":"claude-sonnet-5-5","max_tokens":1024,"system":"You are ...","messages":[{"role":"user","content":"..."}]}
```

### Inferences
- Do not expose a temperature slider for 5.x models; gate it on model `line`/capabilities or just omit. Older models (Sonnet 4.6, Haiku 4.5) still accept 0.0 to 1.0 (docs say the deprecation applies only to models after Opus 4.6).
- Treat `refusal` and `max_tokens` as user-visible conditions, not errors; handle `model_context_window_exceeded`.

### Gaps
- Exact list of which listed models still honor `temperature` is not enumerated beyond "released after Claude Opus 4.6".

## 4. Streaming (SSE)

### Takeaway
Set `stream: true`. Event order: `message_start`, then per block `content_block_start` / N x `content_block_delta` / `content_block_stop`, then `message_delta` (stop_reason + cumulative usage), `message_stop`; `ping` and `error` may appear anywhere. Tool input arrives as `input_json_delta.partial_json` strings to be concatenated and parsed at `content_block_stop`.

### Cited Findings
- Events: message_start, content_block_start, content_block_delta, content_block_stop, message_delta, message_stop, plus `ping` "any number" of times, and `error`. Unknown event types may be added, so ignore unknown ones. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- Delta types: `text_delta{text}`, `input_json_delta{partial_json}`, `thinking_delta{thinking}`, `signature_delta{signature}` (sent just before content_block_stop of a thinking block), `citations_delta`. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming); [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- Tool input: deltas are partial JSON strings; final `tool_use.input` is always an object; accumulate and parse at `content_block_stop`. Current models emit one complete key/value at a time so pauses occur. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- `message_delta.usage` is cumulative; example `{"type":"message_delta","delta":{"stop_reason":"tool_use","stop_sequence":null},"usage":{"output_tokens":89}}`. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- Mid-stream error is delivered as 200 + SSE: `event: error` / `data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}`; normal HTTP error handling does not apply. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming); [Errors](https://platform.claude.com/docs/en/api/errors)
- Recovery: capture partial content; on Claude 4.5 and earlier, resume by passing the partial as an assistant message; on 4.6+, add a user message containing the partial and an instruction to continue (prefill is rejected). Tool-use and thinking blocks cannot be partially recovered; resume from the last text block. — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
- With `display:"omitted"` thinking, the block streams one empty `thinking_delta` then `signature_delta` (faster time to first text token). — [Streaming](https://platform.claude.com/docs/en/build-with-claude/streaming); [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)
- Python SDK: `client.messages.stream(...)` context manager with `text_stream` and `get_final_message()`; `create(stream=True)` yields raw events with less memory. Async identical via `AsyncAnthropic`. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)

### Inferences
- Cancellation: the docs reviewed do not describe a server-side cancel call; closing the HTTP response/context manager (e.g. exiting `with client.messages.stream`, or cancelling the asyncio task) drops the connection. Billing of already-generated tokens on disconnect is not documented (UNVERIFIED). In FastAPI, propagate client disconnect (`request.is_disconnected()`) to close the upstream stream.
- Relay to the UI as your own normalized SSE (text, tool_call, usage, error) and always send a terminal event; treat `error` events as retryable only for overloaded_error/api_error and only before any tool_use block was emitted.

### Gaps
- Explicit cancellation semantics and billing on aborted streams: not found in the pages fetched (UNVERIFIED).

## 5. Tool use and structured output

### Takeaway
Define tools with `name`/`description`/`input_schema`; loop on `stop_reason == "tool_use"` returning `tool_result` blocks first in a single user message. On Opus 5.5, Sonnet 5.5, Fable 5.1 and Mythos 5.1, forced `tool_choice` (`any`/`tool`) returns 400; use `auto` + `strict: true` or `output_config.format` JSON schema outputs.

### Cited Findings
- Tool def: `name` matches `^[a-zA-Z0-9_-]{1,128}$`, `description`, `input_schema` (JSON Schema object), optional `input_examples`, `strict`, `cache_control`, `defer_loading`. — [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- `tool_choice`: `auto` (default with tools), `any`, `tool` (named), `none`; `disable_parallel_tool_use` available on auto/any/tool. Changing `tool_choice` invalidates cached message blocks. — [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools); [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- Forced tool use (`any`/`tool`) returns 400 on Claude Opus 5.5, Sonnet 5.5, Fable 5.1, Mythos 5.1 ("tool_choice: type "tool" and "any" are not supported for this model."), including on count_tokens; also unsupported with manual extended thinking. Forcing a tool skips thinking and suppresses preamble text. — [Errors](https://platform.claude.com/docs/en/api/errors); [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- Loop: response has `stop_reason:"tool_use"` and `tool_use` blocks (`id`, `name`, `input`). Reply as a `user` message with `tool_result` blocks: `tool_use_id`, `content` (string or text/image/document/search_result blocks), `is_error`. tool_result blocks must immediately follow and come FIRST in content; text after them; violating gives 400 ("tool_use ids were found without tool_result blocks immediately after"). — [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- Parallel calls: Claude may emit several `tool_use` blocks in one turn; return one `tool_result` per block in a single user message (per the "Parallel tool use" page, not fetched, and the stop-reason rule "return a tool_result for every tool_use block"). — [Handling stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)
- Tool results are untrusted; keep them inside tool_result blocks (prompt-injection guidance). — [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- Tool-use adds an auto-generated system prompt (extra input tokens). — [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)
- Structured outputs: `output_config: {"format": {"type":"json_schema","schema":{...}}}`; the JSON text comes back in a text content block. Old `output_format`/beta header `structured-outputs-2025-11-13` is deprecated. Supported on all current 5.x models and 4.5+/4.6+ models. — [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Schema limits: `additionalProperties:false` required on objects; no recursive schemas, no min/max numeric or string length constraints, array minItems 0 or 1 only, no external `$ref`; supports anyOf/allOf, enum, const, `$ref/$defs` internal, string formats (date-time, email, uri, uuid...). Violations return 400. — [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Strict tool use: `strict: true`; limits per request 20 strict tools, 24 optional parameters, 16 anyOf/type-array parameters. Compile timeout 180 s; first request with a new schema incurs latency; grammar cached 24 h from last use. — [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Structured output can still be invalid on `stop_reason` `refusal` or `max_tokens`; enum casing may change, compare case-insensitively. Changing `output_config.format` invalidates the prompt cache for that thread. — [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Python helper: `client.messages.parse(..., output_format=PydanticModel)` returns `response.parsed_output`; SDK `@beta_tool` + `client.beta.messages.tool_runner(...)` automates the loop. — [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs); [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- A parameter asking for step-by-step reasoning in tool/schema can trigger `reasoning_extraction` refusal; ask for a short explanation. — [Define tools](https://platform.claude.com/docs/en/agents-and-tools/tool-use/define-tools)

### Inferences
- For "analysis" results, prefer `output_config.format` with a flat schema (all fields required, `additionalProperties:false`) over forced tool_choice, because forced tool use is rejected on the flagship models. Validate with Pydantic anyway (constraints stripped from schema are not enforced by the model).
- Always cap tool-loop iterations and total tokens in your own code.

### Gaps
- Parallel tool use page and `disable_parallel_tool_use` semantics were not fetched directly (listed only in the reference).

## 6. Extended/adaptive thinking, prompt caching, token counting, Batch API

### Takeaway
On 5.x models thinking is adaptive (always on for Opus 5.5/Fable 5.1; Sonnet 5.5 and Haiku 5.5 adaptive); steer with `output_config.effort`. Manual `thinking:{type:"enabled",budget_tokens}` is only for 4.5 and earlier (Opus/Sonnet 4.6 deprecated) and 400s on 4.7+. Prompt caching gives 0.1x (0.05x on Opus/Sonnet 5.5) reads; Batch is 50% off.

### Cited Findings
- Thinking tokens are billed as output tokens even when not returned and count toward `max_tokens`. — [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking)
- Config values: `{"type":"adaptive"}`, `{"type":"enabled","budget_tokens":N}` (N >= 1024 and < max_tokens), `{"type":"disabled"}`, `{"type":"between_tools"}` (Sonnet 5.5 only); `display`: `summarized` | `omitted` (default `omitted` on 5.x models, `summarized` on Opus/Sonnet 4.6 and earlier) | `updates` (beta, header `thinking-display-updates-2026-08-18`). Billed for full thinking tokens, not the summary. — [Thinking](https://platform.claude.com/docs/en/build-with-claude/thinking); [Create a Message](https://platform.claude.com/docs/en/api/messages/create)
- `output_config.effort`: low | medium | high | xhigh | max (per-model support in `capabilities.effort`). — [Create a Message](https://platform.claude.com/docs/en/api/messages/create); [List Models](https://platform.claude.com/docs/en/api/models-list)
- 400 cases: `enabled` on 4.7+; `disabled` on Fable 5.1, Mythos 5.1, Fable 5, Mythos 5, Opus 5.5 (always-on) and on Sonnet 5.5 (use `between_tools`); `adaptive` on 4.5 and earlier; `between_tools` with xhigh/max effort; changing effort mid-conversation with between_tools. — [Errors](https://platform.claude.com/docs/en/api/errors)
- Thinking/redacted_thinking blocks must be passed back unmodified in the latest assistant turn (esp. with tool use), else 400. For accounts created on/after 2026-08-31, replaying a thinking block whose preceding history changed is rejected (`prefix_mismatch_behavior` can be `drop_block` with beta header `thinking-binding-controls-2026-08-01`). — [Errors](https://platform.claude.com/docs/en/api/errors)
- Prompt caching: `cache_control: {"type":"ephemeral"}` (+ optional `"ttl":"1h"`; default 5m). Either one top-level `cache_control` (automatic) or up to 4 explicit block breakpoints in tools/system/messages. Prefix order tools -> system -> messages; 100% identical prefix required; lookback 20 blocks. — [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- Minimum cacheable tokens: 512 for Fable 5.1/Opus 5.5/Sonnet 5.5/Haiku 5.5 (and Opus 5, Sonnet 5, Fable 5); 1,024 for Opus 4.8/Sonnet 5/4.6/4.5; 2,048 Opus 4.7; 4,096 Opus 4.6/4.5, Haiku 4.5. Below minimum silently uncached (check usage fields). — [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- Pricing multipliers on base input: 5m write 1.25x, 1h write 2x, read 0.1x (0.05x Opus 5.5/Sonnet 5.5, 0.025x Fable 5.1/Mythos 5.1); e.g. Sonnet 5.5 $2 base, $2.50 5m write, $4 1h write, $0.10 read. 5m TTL refreshes free on each hit; 1h entries must precede 5m entries. — [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- What invalidates: tool definition changes invalidate everything; `tool_choice` changes invalidate system + messages cache entries... per table, changing thinking/effort invalidates message cache; adding/removing images invalidates tools+system+messages levels as listed. Cache is isolated per workspace on the Claude API. — [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- Cached reads do not count toward ITPM on most models. — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Token counting: `POST /v1/messages/count_tokens` with same body shape as Messages; returns `{"input_tokens": N}`; free; RPM 5,000/10,000/20,000 by tier (Start/Build/Scale), separate from messages limits; estimate only; rejects server tools, MCP connector, url/file sources (use base64). — [Token counting](https://platform.claude.com/docs/en/build-with-claude/token-counting)
- Batch API: `POST /v1/messages/batches`, 50% cost reduction; up to 100,000 requests or 256 MB per batch; most finish within 1 hour, expire after 24 h; results available 29 days; `processing_status` in_progress -> ended; per-request result types succeeded | errored | canceled | expired (only succeeded billed); results JSONL via `results_url`; params validated asynchronously. 300k output tokens with beta header `output-300k-2026-03-24`. — [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing); [Models overview](https://platform.claude.com/docs/en/models/overview)

### Inferences
- For an interactive desktop app, use streaming + prompt caching of stable system/tool prefix (>= 512 tokens on current models). Batch is for background bulk analysis only (async, up to 24 h).
- Show a pre-send token estimate via count_tokens (remember ~30% tokenizer inflation on 4.7+ models).

### Gaps
- Exact per-model thinking default table (thinking page rows 51+) only partially read; rely on `capabilities.thinking` from Models API.
- Automatic caching billing examples on very long context ("long-context pricing") not fetched.

## 7. Errors, rate limits, retries

### Takeaway
Errors are JSON `{type:"error", error:{type,message}, request_id}`. Retry 408/409/429/5xx/connection errors with backoff honoring `retry-after`; do not retry a spend-cap 429 (no `retry-after`, `error.details.error_code: enforced_spend_limit_reached`).

### Cited Findings
- HTTP codes: 400 `invalid_request_error` (also used for other 4xx and for user-set spend limits); 401 `authentication_error`; 402 `billing_error`; 403 `permission_error`; 404 `not_found_error`; 409 `conflict_error`; 413 `request_too_large`; 429 `rate_limit_error`; 500 `api_error`; 504 `timeout_error`; 529 `overloaded_error`. — [Errors](https://platform.claude.com/docs/en/api/errors)
- Error body example: `{"type":"error","error":{"type":"not_found_error","message":"..."},"request_id":"req_011CSHoEeqs5C35K2UUqR7Fy"}`; `type` values may expand. — [Errors](https://platform.claude.com/docs/en/api/errors)
- `request-id` response header (e.g. `req_018EeWyXxfu5pfWkrYcMdjWG`) equals body `request_id`; include when contacting support. Python SDK exposes `message._request_id`. — [Errors](https://platform.claude.com/docs/en/api/errors); [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- 429 headers: `retry-after` (seconds; "Earlier retries will fail"; not on every 429), `anthropic-ratelimit-requests-{limit,remaining,reset}`, `anthropic-ratelimit-tokens-*`, `anthropic-ratelimit-input-tokens-*`, `anthropic-ratelimit-output-tokens-*` (reset values RFC 3339; token remaining rounded to nearest thousand), plus `anthropic-priority-*` for Priority Tier. — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Limits are org-level RPM/ITPM/OTPM per model class, token-bucket (continuous replenishment), may trip on short bursts. Start tier example: Opus 5.5 / Sonnet 5.5 / Haiku 5.5 each 1,000 RPM, 2,000,000 ITPM, 400,000 OTPM; Fable 5.x 1,000 RPM / 500,000 ITPM / 100,000 OTPM. Build: 5,000 RPM / 5M / 1M (Fable 2,000 / 1.5M / 300k). Scale: 10,000 / 10M / 2M (Fable 4,000 / 4M / 800k). Monthly spend caps: Start $500, Build $1,000, Scale $200,000. — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- OTPM is measured on actual generated tokens; `max_tokens` does not count against it. — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- Acceleration limits: sharp usage ramp can produce 429; ramp traffic gradually. 529 happens under high traffic across all users. — [Errors](https://platform.claude.com/docs/en/api/errors)
- Spend-cap 429: body `error.details.error_code = "enforced_spend_limit_reached"`, no `retry-after`, access resumes 00:00 UTC on first of next month; user-set limits return 400 `invalid_request_error` ("You have reached your specified API usage limits"). — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits)
- SDK auto-retries "twice by default" with exponential backoff honoring `retry-after`; Python retries connection errors, 408, 409, 429, >=500; default timeout 10 minutes. — [Errors](https://platform.claude.com/docs/en/api/errors); [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)

### Inferences
- Backoff recommendation: exponential with jitter, start ~1 s, cap ~30-60 s, 3-5 attempts, honor `retry-after` when present; treat 529 like 429; surface 401/402/403/spend-cap 429 to the user immediately with an actionable message.
- Log `request_id` and `anthropic-ratelimit-*-remaining` per call; expose them in a diagnostics panel.

### Gaps
- No official numeric backoff schedule found beyond "exponential backoff"/`retry-after`.
- 403 specifics beyond "permission_error" (e.g. region block) not detailed; supported-regions page not fetched.

## 8. Official SDK vs raw HTTP, what to pin

### Takeaway
Use the official `anthropic` Python SDK (sync + async, streaming helpers, typed errors, retries, `_request_id`); Python 3.10+ required. Pin a version.

### Cited Findings
- `pip install anthropic`; requires Python 3.10 or later; v1 SDK (breaking changes vs 0.x, see MIGRATION.md). — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- Clients: `Anthropic`, `AsyncAnthropic` (optional `anthropic[aiohttp]` + `DefaultAioHttpClient` for concurrency). Config: `api_key`, `max_retries` (default 2), `timeout` (default 10 min; float or `httpx2.Timeout`), `base_url`/`ANTHROPIC_BASE_URL`, `default_headers`, `http_client` (must be an `httpx2` client; proxies via `DefaultHttpxClient(proxy=...)`). `with_options(...)` per request. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- The page states the SDK uses `httpx2` (fork of httpx); passing an `httpx` client raises TypeError; tracing tools patching `httpx` need `httpx2.alias_httpx()`. This is as printed on the docs page; verify against the installed SDK before relying on it. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- Exceptions: `APIConnectionError`, `APITimeoutError`, `BadRequestError` 400, `AuthenticationError` 401, `PermissionDeniedError` 403, `NotFoundError` 404, `ConflictError` 409, `UnprocessableEntityError` 422, `RateLimitError` 429, `InternalServerError` >=500, base `APIStatusError`/`APIError`. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- Raw access: `client.messages.with_raw_response.create(...)` -> `.headers`, `.parse()`; `with_streaming_response`. Logging via `ANTHROPIC_LOG=debug|info`. `anthropic-version` header defaults to `2023-06-01`. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- SemVer, but some type-only/internals changes may ship in minor releases; check `anthropic.__version__`. Beta features via `client.beta.*` with `betas=[...]`. — [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- SDK sets TCP keepalive and rejects non-streaming requests expected >10 min. — [Errors](https://platform.claude.com/docs/en/api/errors)

### Inferences
- Pin `anthropic==<exact tested 1.x>` (or `~=1.x.y`) in the lockfile; the SDK's model-name Literal types lag, so pass model IDs as plain strings (the `model` field accepts any string). Avoid `client.beta.*` surface for core paths; beta headers in the Models list are dated and change.
- Use `AsyncAnthropic` inside FastAPI; one shared client per API key (not per request); create a new client when the user changes the key. Set `max_retries` to 2 and an explicit `timeout` (e.g. 60-120 s for streaming read).
- Raw HTTP is feasible (three headers + JSON + SSE), but you would reimplement retries, SSE parsing, typed errors; only worthwhile to avoid a dependency.

### Gaps
- Exact current SDK version number and release date not captured (PyPI/GitHub README not fetched); UNVERIFIED.

## 9. Safety, privacy, data retention, secret handling

### Takeaway
API inputs/outputs are not retained by default except as needed; data is never used for training without permission; Fable/Mythos 5.x require 30-day retention; flagged content may be kept up to 2 years. Never log keys; redact before sending.

### Cited Findings
- "Retained data is never used for model training without your express permission." "Conversation content ... is not retained by default; the exception is Covered Models, which require 30-day retention." — [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- ZDR is per-organization and by contract; Messages and Token Counting APIs eligible for listed features; Files API, code execution containers (up to 30 days), MCP connector, skills are not ZDR. Batch/structured-outputs eligibility per feature table (structured outputs: JSON schema cached up to 24 h). — [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention); [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- Even with ZDR/HIPAA, Anthropic may retain flagged inputs/outputs "for up to 2 years". Commercial retention policy is on privacy.claude.com (linked, not fetched). — [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- Key hygiene: "Store API keys in a secrets manager, rotate them periodically, and disable or delete any key you suspect has leaked." — [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication)
- Untrusted tool content (web pages, email, uploads) should be kept in tool_result blocks; indirect prompt injection guidance. — [Handle tool calls](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls)
- Data-residency: `inference_geo` field exists on requests/usage (values like `us`, `global`); rate limits are shared across geos. — [Rate limits](https://platform.claude.com/docs/en/api/rate-limits); [Create a Message](https://platform.claude.com/docs/en/api/messages/create)

### Inferences
- Store user keys in the OS keychain (not config/DB), load into memory only, never log headers (`x-api-key`, `Authorization`); redact in SDK debug logs (`ANTHROPIC_LOG=debug` prints request details; avoid in production). Log `request_id` only.
- Redact secrets/PII (API keys, tokens, `.env` content, private keys) client-side before sending; warn that content leaves the device; send `metadata.user_id` only as an opaque hash.
- Disclose to users: default no retention/training for API data, but flagged content may be held; org-level ZDR is the customer's contractual arrangement, not something the app can toggle.

### Gaps
- Commercial retention TTL numbers (standard log retention days) are on privacy.claude.com, not fetched: UNVERIFIED.
- Whether `ANTHROPIC_LOG=debug` redacts the key is not documented: UNVERIFIED.
