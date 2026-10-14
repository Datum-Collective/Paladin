# OpenAI API integration as a first-class provider (desktop app, Python FastAPI backend)

Research date: 2026-10-14. Primary sources: developers.openai.com (platform.openai.com/docs 301-redirects there) and the openai-python README. Note: platform.openai.com/docs/api-reference/* returned HTTP 403 to the fetch tool, so API-reference pages were read via developers.openai.com where possible. The fetch tool summarizes pages with a small model; exact wording of quoted strings should be re-checked against the live page before hard-coding.

## Authentication, headers, key validation

### Takeaway
Use `Authorization: Bearer <key>`; add `OpenAI-Organization` / `OpenAI-Project` only when needed; log `x-request-id`. The cheapest key check is most likely `GET /v1/models` (UNVERIFIED as an officially documented "validate" method).

### Cited Findings
- Credentials are sent as an HTTP Bearer token in the `Authorization` header; the token can be an API key or a short-lived access token from workload identity federation. — [API overview](https://developers.openai.com/api/reference/overview)
- Keys must be kept secret, not exposed in browsers/apps, loaded server-side from env var or key management service. Revoked keys stop working within seconds; other auth changes can take up to 15 minutes. — [API overview](https://developers.openai.com/api/reference/overview)
- `OpenAI-Organization` and `OpenAI-Project` headers are for users in multiple organizations or using a legacy user API key to access projects; usage is billed to the specified org/project. Separate Admin API key for Administration endpoints. — [API overview](https://developers.openai.com/api/reference/overview)
- Every response carries `x-request-id`; official libraries expose it on response objects. A client-supplied `X-Client-Request-Id` header (ASCII only, up to 512 chars, unique per request, invalid value gives 400) is not added automatically and helps support trace timed-out requests. — [API overview](https://developers.openai.com/api/reference/overview)
- Project-scoped token limits appear in rate-limit headers (`x-ratelimit-*-project-tokens`). — [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Data residency is configured per project; regional processing can be selected per request with a domain prefix such as `us.api.openai.com` / `eu.api.openai.com` (approval needed for some regions). — [Your data](https://developers.openai.com/api/docs/guides/your-data)

### Inferences
- Validate a key by calling `GET /v1/models` (authenticated, no token cost); 401 means invalid/revoked, 403 may mean permission/region/project scope. A project key restricted from the Models endpoint could give 403 even if the key is valid, so treat 401 as invalid and others as "unverified".
- Store the key in the OS keychain, never in logs; send only from the FastAPI backend.

### Gaps
- Official docs fetched did not describe project keys (`sk-proj-...`) in detail or document a "validate key" endpoint. UNVERIFIED.

## Model discovery and current models

### Takeaway
Models API returns only minimal fields (no capability flags), so capability filtering must be done by app-maintained ID allowlists/prefix rules. Current docs list the GPT-6 family as flagship; several older models are shut down.

### Cited Findings
- `GET /models` returns `{object:"list", data:[Model]}`; `GET /models/{model}` returns one Model. Model fields: `id`, `created` (unix seconds), `object:"model"`, `owned_by`, and optional `shutdown_date` (string or null). — [Models reference](https://developers.openai.com/api/reference/resources/models)
- Flagship models listed (all text+image input, text output, functions, web search, file search, computer use; 1.05M context, 128K max output): `gpt-6-astra` (reasoning low/medium/high/xhigh/max; $10/$50 per MTok), `gpt-6.1-sol` ($2/$10), `gpt-6-luna` (adds `none`; $0.10/$0.50). — [Models](https://developers.openai.com/api/docs/models)
- Other IDs listed: `gpt-5.6-cyber`, `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare`, `gpt-realtime-2.1`, `gpt-4o-mini-tts`, `gpt-transcribe`, `gpt-4o-transcribe`. `gpt-realtime-mini` marked deprecated. — [Models](https://developers.openai.com/api/docs/models)
- Shutdowns: `o3-deep-research` and `o4-mini-deep-research` July 23, 2026 (replacement `gpt-5.6-sol`); `gpt-5-chat-latest`, `gpt-5.1-chat-latest` July 23, 2026; `gpt-5.2-chat-latest`, `gpt-5.3-chat-latest` Aug 10, 2026; Assistants API Aug 26, 2026 (replace with Responses + Conversations). — [Deprecations](https://developers.openai.com/api/docs/deprecations)
- Docs are internally inconsistent on names (pages mention `gpt-5.6-sol`, `gpt-6.1-sol`, `gpt-6-sol`, GPT-5.5); treat exact IDs as to-be-confirmed against live `/v1/models`. — [Reasoning](https://developers.openai.com/api/docs/guides/reasoning), [Deprecations](https://developers.openai.com/api/docs/guides/../deprecations)

### Inferences
- To filter to text/reasoning-capable models: exclude IDs containing `image`, `tts`, `transcribe`, `realtime`, `live`, `whisper`, `embedding`, `moderation`; optionally keep a curated list of known-good IDs and surface the rest under "other". Honor `shutdown_date` by hiding/warning.
- Don't hard-code the model list; fetch `/v1/models` at runtime with a fallback default.

### Gaps
- No capability/context-window fields in the Models API; no official "is chat model" filter documented.

## Responses API vs Chat Completions; reasoning; output limits

### Takeaway
Responses API is recommended for all new projects; Chat Completions remains supported (and is the lowest-common-denominator for OpenAI-compatible servers).

### Cited Findings
- Docs recommend Responses for all new projects; Chat Completions remains supported. — [Migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- Differences: `messages` vs `input` (string or Items) plus top-level `instructions`; `choices[].message` vs `output` array of typed Items (`reasoning`, `message`, `function_call`) with `output_text` SDK helper; no `n` in Responses; function definitions internally tagged in Responses; `response_format` becomes `text.format`; streaming typed events instead of delta chunks; state via `previous_response_id`, item replay, or Conversations API (prior input tokens still billed). — [Migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- Responses stores by default; Chat Completions stores by default only for new accounts; `store:false` disables. — [Migrate to Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- Reasoning effort values are model dependent (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`); Astra rejects `none` (400); Sol rejects `none`/`minimal`, default `medium`. `reasoning.summary` opt-in (`auto` is most detailed); raw reasoning not exposed. — [Reasoning](https://developers.openai.com/api/docs/guides/reasoning)
- `max_output_tokens` caps visible plus reasoning tokens; hitting it yields `status: incomplete`, `incomplete_details.reason: max_output_tokens`, possibly with no visible output; docs recommend reserving at least 25,000 tokens initially; reasoning count at `usage.output_tokens_details.reasoning_tokens`. — [Reasoning](https://developers.openai.com/api/docs/guides/reasoning)
- With `store:false`/ZDR, reasoning items include `encrypted_content` by default and should be replayed. — [Reasoning](https://developers.openai.com/api/docs/guides/reasoning)

### Inferences
- Minimal request: `{"model","instructions":"<system prompt>","input":[{"role":"user","content":"..."}],"reasoning":{"effort":"medium"},"max_output_tokens":N,"store":false}`. "developer" role messages / `instructions` serve as the system prompt (developer-message details not covered by fetched pages; UNVERIFIED).
- Abstract provider layer should map effort per-model and clamp unsupported values.

### Gaps
- Full Responses `create` reference (403 on platform.openai.com) was not read; exact field list not verified here.

## Streaming

### Takeaway
Responses streams semantic typed events; accumulate `response.output_text.delta` and `response.function_call_arguments.delta`, finalize on `.done`/`response.completed`.

### Cited Findings
- SDK event classes include ResponseCreated, InProgress, Failed, Completed, OutputItemAdded/Done, ContentPartAdded/Done, OutputTextDelta, OutputTextAnnotationAdded, TextDone, RefusalDelta/Done, FunctionCallArgumentsDelta/Done, FileSearchCall*, CodeInterpreter*, and `Error`. Wire strings documented on the page: `response.created`, `response.output_text.delta` (with `event.delta`), `response.completed`, `error` (with `event.message`). — [Streaming responses](https://developers.openai.com/api/docs/guides/streaming-responses)
- Background + stream: each event has `sequence_number`; resume dropped stream with `starting_after`; response keeps running while disconnected; only streamable if created with stream enabled. Cancel via cancel endpoint; for a synchronous response, terminate the connection. — [Background mode](https://developers.openai.com/api/docs/guides/background)
- Python SDK: streaming consumption is not auto-retried; read timeouts surface as `APITimeoutError`/`APIConnectionError`. — [openai-python README](https://raw.githubusercontent.com/openai/openai-python/main/README.md)

### Inferences
- Wire names by convention (UNVERIFIED on fetched page): `response.output_item.added`, `response.function_call_arguments.delta`/`.done`, `response.refusal.delta`, `response.failed`, `response.incomplete`. Key function-call deltas by `item_id`/`output_index`.
- Cancellation from FastAPI: close the httpx stream when the client disconnects; mid-stream errors arrive as `error` / `response.failed` events or as exceptions, with no auto-retry, so the app must resume or restart.

### Gaps
- Chat Completions SSE shape (`chat.completion.chunk`, `delta.tool_calls`, `stream_options.include_usage`, `[DONE]`) not fetched; UNVERIFIED here.

## Tool calling and Structured Outputs

### Takeaway
Define function tools with strict schemas; loop on `function_call` items, replying with `function_call_output` keyed by `call_id`.

### Cited Findings
- Function tool: `type:"function"`, `name`, `description`, `parameters` (JSON Schema), `strict`. `tool_choice`: `auto` (default), `required`, forced `{"type":"function","name":...}`, `allowed_tools`, `none`. `parallel_tool_calls:false` limits to at most one call. — [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- Loop: read `function_call` items (`call_id`, `name`, JSON string `arguments`); append model output items plus a `function_call_output` item (`call_id`, string `output`); resend; repeat. Reasoning items must be passed back for reasoning models. Use `call_id`, not item `id`. — [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- Strict mode requires `additionalProperties:false` on all objects and all properties in `required`; optional via `["string","null"]`. Responses normalizes to strict where possible; Chat Completions defaults non-strict. — [Function calling](https://developers.openai.com/api/docs/guides/function-calling)
- Structured Outputs: `text.format = {type:"json_schema", name, schema, strict:true}`. Refusals show up as a `refusal` content part not following the schema; check before parsing; `incomplete` with `max_output_tokens` may truncate JSON; first request per new schema has extra latency. — [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

### Gaps
- Supported JSON Schema subset and limits (nesting/property counts) were in the truncated part of the page; not verified.

## Errors and rate limits

### Takeaway
Branch on `error.code`, not just status/type; retry 429 rate limits, 5xx, 503; never retry billing/quota errors.

### Cited Findings
- 429 covers rate limits (`rate_limit_error`, `slow_down`) and billing/spend (`credit_balance_exhausted`, `organization_spend_limit_exceeded`, `project_spend_limit_exceeded`, `organization_usage_limit_exceeded`); `error.type` may still be `insufficient_quota`, so inspect `error.code`. 503 `server_is_overloaded`; 500 server error; 400/401/403 not retryable. Error fields: `code`, `type`, `param`. — [Error codes](https://developers.openai.com/api/docs/guides/error-codes)
- Honor `Retry-After` as a minimum; otherwise exponential backoff with jitter, capped attempts/time. Failed requests still count toward limits. Disable SDK retries or count them to avoid nested retry multiplication. — [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Headers: `x-ratelimit-limit-requests`, `-limit-tokens`, `-remaining-requests`, `-remaining-tokens`, `-reset-requests`, `-reset-tokens`, plus project token variants; `Retry-After` on some 429 and on 503. — [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits)

### Gaps
- Exact JSON error envelope (`{"error":{message,type,param,code}}`) not shown on fetched page; widely used but UNVERIFIED here.

## Official Python SDK

### Cited Findings
- Retries default 2 (connection errors, 408, 409, 429, 5xx) with exponential backoff; `max_retries` on client or `with_options()`. Default timeout 10 minutes; `timeout` float or httpx Timeout; raises `APITimeoutError`. — [openai-python](https://raw.githubusercontent.com/openai/openai-python/main/README.md)
- Errors: `APIError` base; `APIConnectionError`; `APIStatusError` (400 BadRequestError, 401 AuthenticationError, 403 PermissionDeniedError, 404 NotFoundError, 422 UnprocessableEntityError, 429 RateLimitError, 5xx InternalServerError); `exc.request_id`; `_request_id` on responses. — [openai-python](https://raw.githubusercontent.com/openai/openai-python/main/README.md)
- `AsyncOpenAI` for async; `openai[aiohttp]` optional; `.with_raw_response` exposes headers (use for x-ratelimit-*); `base_url` arg or `OPENAI_BASE_URL`. SemVer-ish, breaking changes may ship in minor releases; `openai.__version__`. — [openai-python](https://raw.githubusercontent.com/openai/openai-python/main/README.md)

### Inferences
- Pin an exact version (e.g. `openai==X.Y.Z`) in lockfile given minor-release breaks; use `AsyncOpenAI` in FastAPI; set explicit `timeout` and `max_retries`.

## Data controls

### Cited Findings
- Abuse-monitoring logs kept up to 30 days by default; `store` on `/v1/responses` and `/v1/chat/completions` controls application-state retention (at least 30 days when true); ZDR requires approval and forces store false; background mode keeps data ~10 minutes and is incompatible with ZDR; Conversations/files/assistants not ZDR-eligible. — [Your data](https://developers.openai.com/api/docs/guides/your-data)

### Inferences
- Default the app to `store:false` for privacy (replay items for state), and never log Authorization headers or full request bodies.

## OpenAI-compatible base_url (local models)

### Cited Findings
- SDK accepts `base_url` / `OPENAI_BASE_URL`. — [openai-python](https://raw.githubusercontent.com/openai/openai-python/main/README.md)

### Gaps
- Differences for third-party/local servers (Ollama, LM Studio, vLLM) are not covered in OpenAI primary docs; UNVERIFIED. Practical expectation (inference): most support only Chat Completions, may ignore `reasoning`, `store`, strict schemas, and `/v1/models` fields; Responses API support varies, so capability-probe and fall back to Chat Completions.

## Deep Research

### Takeaway
Deep research models run through the Responses API in background mode, but the docs list `o3-deep-research` / `o4-mini-deep-research` as shut down July 23, 2026, replaced by `gpt-5.6-sol`; so as of Oct 2026 these should not be targeted.

### Cited Findings
- Models `o3-deep-research` and `o4-mini-deep-research` (shut down July 23, 2026; replacement `gpt-5.6-sol`; "changing the model ID alone is not a complete migration"). — [Deep research guide](https://developers.openai.com/api/docs/guides/deep-research), [Deprecations](https://developers.openai.com/api/docs/deprecations)
- Responses API, `background:true`, must include at least one data source: `web_search_preview`, `file_search` (`vector_store_ids`, max two), or remote `mcp` (`server_label`, `server_url`, `require_approval:"never"`; server must expose `search` and `fetch`); optional `code_interpreter` (`container:{type:"auto"}`). Function calling unsupported. — [Deep research guide](https://developers.openai.com/api/docs/guides/deep-research)
- Runs can take tens of minutes; poll until not `queued`/`in_progress`, or use webhooks; examples use 3600s client timeout; `max_tool_calls` caps cost/latency; `reasoning:{summary:"auto"}` available. Output array holds `web_search_call` (actions `search`, `open_page`, `find_in_page`), `code_interpreter_call`, `mcp_tool_call`, `file_search_call`, then `message` with `output_text` and `annotations` (`url`,`title`,`start_index`,`end_index`); citations must be visible and clickable. — [Deep research guide](https://developers.openai.com/api/docs/guides/deep-research)
- No built-in clarification/rewrite step; optionally pre-process with a smaller model. Prompt-injection risks; mitigations: trusted MCP servers, log tool calls, stage private vs public, validate args, screen links. — [Deep research guide](https://developers.openai.com/api/docs/guides/deep-research)
- Background cancel endpoint; data retained about 10 minutes. — [Background mode](https://developers.openai.com/api/docs/guides/background)

### Inferences
- For research-style capability today, use a current flagship model with the built-in web search tool in background mode (exact replacement tool type name, `web_search` vs `web_search_preview`, UNVERIFIED), and implement own plan/search/synthesize loop with citation annotations.
