# Historical BTB workflow baseline

`baseline.sanitized.json` is a review-only copy of the user-supplied BTB Teaching
Assistant 1.0 export. It is not the current Grounded Tutor generator, a supported
production configuration, or an automatically runnable import.

The historical graph rewrites a question, classifies it into fixed BTB topics,
searches topic-specific knowledge bases, and answers or refuses. Its AI terminology
branch includes an HTTP web-search fallback when knowledge-base evidence is absent.
The 13 node types, node identifiers, edges and public teaching prompts are retained.
Graph-local identifiers are wiring references, not account identifiers.

The sanitizer removes private binding/authentication fields and key/value entries,
including dataset selections, request credentials and account identifiers. It removes
UI value-description schemas, recursively processes JSON-string HTTP bodies, and
replaces HTTP(S) URLs and recognizable credential/24-hex identifier text. Dataset
bindings and HTTP endpoints must be configured from scratch before any independent
experiment; this repository does not enable them. Public prompts retain the original
BTB course context as historical design, without including private course documents.

Grounded Tutor differs: local services own dynamic Workspaces, READY filtering,
structured citations, history, plans and scoring. Its dedicated generator performs
no extra retrieval or external actions. Configure that using
[the current generation guide](../docs/fastgpt-generation.md), not this baseline.

## Reproducing a sanitized copy

Keep the original export outside the repository. Use explicit paths and a fresh
output filename; the command refuses to overwrite any existing output or its input.

```sh
python3 scripts/sanitize_fastgpt_export.py /path/to/private-export.json /path/to/new-sanitized-copy.json
```

The tool accepts UTF-8 exports with or without a BOM and never prints removed values
or parser details. It is a targeted convenience tool, not a universal secret detector:
arbitrary secrets or private prose under unrecognized fields can survive. Manually
review every output, compare graph structure, and run publication/secret checks
before staging or sharing it. Never commit the original or use it as a test fixture.

The current copy was generated from the owner's local export and checked for known
private fields and structural preservation. It was not imported, executed, or
published to FastGPT; no remote application was changed by this release task.
