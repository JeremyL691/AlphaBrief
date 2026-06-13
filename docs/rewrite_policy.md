# AlphaBrief Rewrite Policy

AlphaBrief is an owned implementation. Third-party projects in
`_reference_sources/` are reference material only.

## Allowed

1. Read reference projects to understand product flows, module boundaries,
   abstractions, and test scenarios.
2. Write natural-language behavior notes in `docs/reference_notes/`.
3. Implement AlphaBrief behavior from those notes using original names,
   interfaces, tests, and structure.

## Forbidden

1. Import code from `_reference_sources/`.
2. Copy, translate, or lightly rewrite source files.
3. Preserve class names, function names, prompt text, comments, test fixtures,
   or file structure from reference projects.
4. Ask an agent to migrate or adapt a reference file directly.
5. Keep reference files open while implementing matching AlphaBrief code.

## Clean-Room Flow

```text
Read Reference
-> Write Behavior Spec
-> Close Reference
-> Implement AlphaBrief Version
-> Write AlphaBrief Tests
-> Similarity Review
```
