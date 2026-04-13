# Mark II Runbook

`Mark II` now supports the broader pattern:

1. take an existing code file
2. or take a task prompt
3. build or load the app
4. break it with a task-specific swarm
5. heal it with one or more models
6. promote the best surviving mark

The current implementation is generalized around a `TaskSpec`, but the runtime still targets `fastapi_single_file` tasks. The bundled attack profile is `payment_api`.

## Main Files

- Main loop: `/Users/karthiklucky/llm/stark_labs/mark_ii/architect.py`
- Task spec loader: `/Users/karthiklucky/llm/stark_labs/mark_ii/task_spec.py`
- Default task spec: `/Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api.json`
- Prompt-driven task spec: `/Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api_prompt.json`
- Validator: `/Users/karthiklucky/llm/stark_labs/mark_ii/validator.py`
- ASGI harness: `/Users/karthiklucky/llm/stark_labs/mark_ii/asgi_harness.py`
- Swarm: `/Users/karthiklucky/llm/stark_labs/mark_ii/swarm_strike.py`
- Providers: `/Users/karthiklucky/llm/stark_labs/mark_ii/providers.py`
- Patch memory: `/Users/karthiklucky/llm/stark_labs/mark_ii/patch_memory.json`

## Provider Config

Put API keys in `/Users/karthiklucky/llm/stark_labs/.env`:

```env
OPENAI_API_KEY=...
OPENAI_PATCH_MODEL=gpt-5.4-2026-03-05

ANTHROPIC_API_KEY=...
ANTHROPIC_PATCH_MODEL=claude-sonnet-4-20250514

DEEPSEEK_API_KEY=...
DEEPSEEK_PATCH_MODEL=deepseek-reasoner
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

## Existing Code Input

Validate an existing source file against a task spec:

```bash
python3 /Users/karthiklucky/llm/stark_labs/mark_ii/validate_target.py \
  --task-spec /Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api.json \
  --file /Users/karthiklucky/llm/stark_labs/mark_ii/target_api.py
```

Run the full heal loop on an existing file:

```bash
python3 /Users/karthiklucky/llm/stark_labs/mark_ii/architect.py \
  --task-spec /Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api.json \
  --source-file /Users/karthiklucky/llm/stark_labs/mark_ii/target_api.py
```

## Prompt Input

Run the prompt-driven build-break-heal flow:

```bash
python3 /Users/karthiklucky/llm/stark_labs/mark_ii/architect.py \
  --task-spec /Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api_prompt.json
```

Or override the builder prompt directly:

```bash
python3 /Users/karthiklucky/llm/stark_labs/mark_ii/architect.py \
  --task-spec /Users/karthiklucky/llm/stark_labs/mark_ii/task_specs/payment_api_prompt.json \
  --bootstrap-prompt "Build a FastAPI API with ..."
```

## Validation Order

For every candidate, `Mark II` runs:

1. `syntax`
2. `startup`
3. `openapi`
4. `smoke`
5. `swarm`
6. `score`

## Current Limits

- Generalized input is ready through `TaskSpec`
- Prompt bootstrap is working
- Current framework support is still only `fastapi_single_file`
- Current bundled attack profile is still only `payment_api`
- Claude and DeepSeek are wired in the provider layer, but they need their API keys and installed dependencies to run
