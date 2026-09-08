# Security and data boundaries

This prototype is for a trusted local user. Bind services to loopback and run one
API worker. There is no account authentication or safe shared/public API deployment.
Workspace scoping prevents accidental cross-topic references but does not establish
user authorization. Keep local administration disabled unless deliberately inspecting
local traces. A read-only UI is not a replacement for API access controls.

Real configuration belongs in ignored `apps/api/.env`. The two tracked `.env.example`
files contain blank keys and fake defaults. Never put credentials in frontend build
variables. Local database files and raw reports must not be committed. Source text,
questions, answers and citation snapshots may be retained in SQLite and traces;
protect the filesystem and backups accordingly. No at-rest encryption or secure
file-erasure guarantee is provided by this application.

In live mode, uploaded material reaches FastGPT for processing and retrieval;
selected excerpts and the question reach the configured generation provider.
If that generator is FastGPT, it uses the model configured in its application.
Provider retention policies are separate from local storage. Use only material you
are authorized to send. Removing local state is not a promise that provider backups
or logs have been erased.

Do not include credentials, private account/Dataset IDs, real student material or
private course content in issues, logs you share, screenshots, fixtures or reports.
Use synthetic reproductions. Raw evaluation and trace artifacts may contain excerpts;
inspect and redact before sharing. The numeric summary is deliberately restricted,
and public reports still require their separate release review.

The publication guard checks staged and working files and known local secrets without
echoing matches. Its two exact example-file exceptions do not bypass content scanning.
Full-history Gitleaks in CI complements this guard; no scanner detects every possible
secret or unauthorized document. If a key is exposed, revoke it at the provider and
remove exposed copies; deleting one file does not remove Git history.

Document text is untrusted evidence, not instructions. Generation output is schema
validated and citations are resolved against allowed evidence. This limits actions
and fabricated identifiers but cannot guarantee semantic truth or complete prompt
injection resistance. Keep generator tools and external-action workflow nodes off.

See [contribution reporting guidance](../CONTRIBUTING.md) for private disclosures.
