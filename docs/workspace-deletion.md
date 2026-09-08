# Workspace deletion

Desktop topic rail includes an explicit Delete action. Confirmation names the
topic and warns that its sources, conversation history, learning progress and
FastGPT dataset will be permanently removed. Cancel has initial focus. Pending
writes disable deletion; a failed request stays in the dialog for retry.

DELETE /api/workspaces/{id} uses the existing app-scoped workspace lock. It deletes
the remote dataset first, then the scoped local relation graph in one transaction.
Other workspace rows remain unchanged. Missing local workspace returns204; demo
writes return403; busy/pending requests return409; provider failures return502.
No migration or new dependency is required. Single-process local deployment only.

A lost response/local commit failure is retryable. Only the exact upstream
FastGPT missing-dataset envelope (code501002, statusText unExistDataset, data:null)
on the dataset DELETE endpoint is accepted as already absent; authentication,
generic404 and mismatched envelopes remain failures. References:
https://github.com/labring/FastGPT/blob/main/packages/global/common/error/code/dataset.ts
https://github.com/labring/FastGPT/blob/main/packages/service/support/permission/dataset/auth.ts
Cloud and local storage are not an atomic transaction: a failure may leave the
local topic listed after its cloud dataset is gone; the confirmation explains
that retry continues cleanup. Unknown provider responses fail closed.

On success the UI cancels old topic-list requests before replacing the list,
removes scoped query caches/drafts and clears the URL/citation when deleting the
last topic. A regression delays a pre-delete list response to verify it cannot
restore the removed topic.

E2E isolation now uses backend8018 and a server-only API_PROXY_TARGET for both
browser test servers. Test setup calls relative/api through the test frontend;
normal development keeps8000. Three isolation regressions were red before fixes.

2026-09-08 verification: backend980 passed/7 opted-out live skips; frontend69
passed; production build/Ruff/whitespace passed. Full desktop suite18 passed and
18 cross-mode skips; final deletion-specific browser confirmation recorded in
session output. Independent review caught the old-list response race, then its
regression was observed red and fixed. No GitHub push/publication performed.

The six Learning/Other/Dismiss local-1280x720/local-1440x900 test topics from the
previous faulty test setup were deleted through the real application endpoint,
all204. Before/after original topic summaries matched exactly.
