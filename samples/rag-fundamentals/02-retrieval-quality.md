# Retrieval quality and evaluation

Full-text retrieval matches terms in indexed text. It can help with exact names
and identifiers. Semantic retrieval compares representations of meaning and can
find related phrasing without identical words. Neither method guarantees that
the result answers the question. Hybrid retrieval combines signals from both.

A reranker reorders retrieved candidates using an additional relevance judgment.
It can improve the ordering but cannot recover a document that never reached its
candidate set. Larger candidate sets can add cost and latency, so measure the
tradeoff on representative questions rather than assuming more is always better.

Example: a document says "postpone the workshop" while a learner asks about
"delaying the session". Semantic retrieval may connect the phrases. An exact
workshop code may instead benefit from term matching. Check actual results before
choosing a retrieval strategy.

Evaluate retrieval separately from answer generation. For retrieval, ask whether
the selected chunks contain the needed evidence. For answers, check factual
support, citation correctness, and whether missing evidence is acknowledged.
Also measure latency and service failures. A well-formed JSON answer can still
be factually wrong, and a passing software test does not establish teaching quality.

A small evaluation set should include supported questions, unsupported questions,
ambiguous questions, and documents containing misleading instructions. Record
failures and rerun the same cases after changes. Keep examples used for tuning
separate from held-out evaluation questions when estimating generalization.
