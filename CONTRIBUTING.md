# Contributing

Start with the [local setup](README.md) and discuss scope before large changes.
Keep changes small and reuse existing contracts. For behavior changes, add a
regression test that fails before the fix; run relevant tests and `make verify-learning`
before proposing integration. Explain the problem, resulting behavior, checks run,
and any unresolved limitations. Never describe fake-provider results as model quality.

Declare that any contributed sample data is original or redistributable under a
stated compatible license. Include provenance and update the sample SHA-256 manifest
when a sample changes. Do not contribute real student work or private course material.

Run `bash scripts/check_public_files.sh` after staging. It scans both staged and
working files but does not replace full-history secret scanning. Never attach raw
traces, evaluation reports, keys, private dataset IDs or unredacted screenshots to
issues or changes. See [security and data](docs/security-and-data.md).

For sensitive reports, do not open a public issue with the exploit data or secrets.
Use a repository private security-reporting channel if one is available; otherwise
request a private contact without including sensitive details. No contact address
or hosted repository is asserted before publication.
