# RAG fundamentals

Retrieval-augmented generation (RAG) supplies retrieved material to a language
model before it writes an answer. Its main components are a document store,
a retrieval step, an answer generator, and checks on the generated answer.

During ingestion, documents are split into chunks. Each chunk should retain enough
context to be understandable and metadata that links it to its source. Very small
chunks can lose context; very large chunks can mix relevant and irrelevant text.
Overlap can preserve a sentence crossing a boundary, but also duplicates text.
There is no chunk size that works best for every collection and question.

During a question, retrieval selects candidate chunks. The generator receives the
question and selected evidence. Grounding means checking the answer against that
evidence. A citation helps the reader locate support; its mere presence does not
prove the claim is correct. A system should distinguish unsupported questions
from failures to reach its retrieval or generation service.

Example: a note states that a workshop starts at 09:00. A supported answer can
repeat that time and cite the note. If the note says nothing about the room,
the system should acknowledge the missing information instead of inventing one.

In Grounded Tutor, a source is available to grounded retrieval only after its
processed version has been reviewed and accepted. Uploaded content remains data,
not permission to follow instructions embedded in the document.
