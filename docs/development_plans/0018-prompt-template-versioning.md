# Development Plan 0018: Prompt Template Versioning MVP

## Goal

Add the minimal local prompt template versioning boundary for Phase 2 model
requests.

## Changes

1. Add `PromptTemplate`, `RenderedPrompt`, `PromptTemplateRegistry`, and
   `PromptTemplateError`.
2. Render `{{ variable }}` placeholders from explicit string variables.
3. Produce stable `prompt_version` values as `template_id:version`.
4. Reject missing, extra, blank, duplicate, or invalid variables.
5. Keep registry selection explicit by template ID and version.
6. Export the public API from `alphabrief_models`.
7. Add tests and documentation.

## Out of Scope

1. Loading templates from files, databases, or environment variables.
2. Secret storage or secret interpolation.
3. Provider calls, retries, model selection, or DailyAlphaBrief generation
   changes.
4. Any implementation copied from `_reference_sources/`.

## Acceptance

1. `tests/test_prompt_templates.py` passes.
2. Full project tests pass.
3. Ruff and mypy pass.
4. Rendered prompts can be used to build `ModelRequest` objects.
