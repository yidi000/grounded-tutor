<div align="center">

# Grounded Tutor

[简体中文](README.md) · **English**

### Study your own materials. Follow every answer back to its sources.

Import notes and lectures · Inspect citations · Learn and check your understanding

[![Release verification](https://github.com/yidi000/grounded-tutor/actions/workflows/ci.yml/badge.svg)](https://github.com/yidi000/grounded-tutor/actions/workflows/ci.yml)
[![MIT License](https://img.shields.io/badge/License-MIT-713E4B.svg)](LICENSE)

[Quick start](#quick-start) · [Connect a model](#connect-a-model) · [Deployment guide](docs/local-development.md) · [Report an issue](https://github.com/yidi000/grounded-tutor/issues)

</div>

![Grounded Tutor desktop: topic navigation on the left, answers in the center, and source excerpts on the right](docs/images/grounded-tutor-desktop.png)

<p align="center"><sub>Actual interface using the bundled public RAG example. No private material is shown. The application UI is currently in Chinese.</sub></p>

## Go beyond getting an answer

Grounded Tutor is a local learning workspace for your course materials. Organize documents into topics, ask questions, and follow citations back to the original text. When you want to go deeper, use short diagnostics, learning paths, explanations, and understanding checks.

| Ask and verify | Learn and practice | Organize your materials |
| :--- | :--- | :--- |
| Open numbered citations to inspect source excerpts | Build a finite learning path from a short diagnostic | Upload files or paste text; preview before accepting |
| Restore saved answers and citations after a refresh | Read explanations, answer checks, and review feedback | Keep each topic's sources, history, and progress separate |
| Get a clear notice when evidence is insufficient | Pause a lesson, ask a question, then resume | Create, rename, and delete topics with confirmation |

## Quick start

**Requirements: Python 3.12 / 3.13, Node.js 24, npm, Git, and Make.** The commands below target a macOS or Linux terminal.

**1 · Download and install**

```sh
git clone https://github.com/yidi000/grounded-tutor.git
cd grounded-tutor
python3 -m venv .venv
.venv/bin/python -m pip install -e 'apps/api[test]'
npm --prefix apps/web ci
```

**2 · Initialize and start the backend**

```sh
test -f apps/api/.env || cp apps/api/.env.example apps/api/.env
.venv/bin/alembic -c apps/api/alembic.ini upgrade head
make api-dev
```

**3 · Open another terminal and start the frontend**

Run from the same `grounded-tutor` directory:

```sh
VITE_APP_MODE=local npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173**, create a topic, import the [sample material](samples/rag-fundamentals/README.md), and review and accept it to explore the workflow.

> The default configuration uses **fake providers**: no API key is needed, but answers are fixed test content. To study real documents with a model, complete the setup below.

## Connect a model

Set `EXTERNAL_MODE=live` in your local `apps/api/.env`, configure FastGPT and the generation provider, then restart the backend and create a new topic.

| Component | Responsibility |
| :--- | :--- |
| **Grounded Tutor** | Interface, topics, history, learning workflow, and local data |
| **FastGPT** | Document processing, organization, and retrieval |
| **Generation model** | Compose answers from retrieved excerpts through a dedicated FastGPT app or a compatible endpoint |

**[Follow the step-by-step configuration guide →](docs/fastgpt-generation.md)**

Keep keys only in your Git-ignored local `.env`; never place them in the frontend or commit them to GitHub. When you use cloud FastGPT or model providers, relevant material is sent to those configured services. Running locally does not mean running fully offline.

<details>
<summary><strong>Want to explore the interface without a backend?</strong></summary>

After installing frontend dependencies, run:

```sh
VITE_APP_MODE=demo_read_only npm --prefix apps/web run dev -- --host 127.0.0.1 --port 5173
```

This opens a fixed local read-only example with inspectable citations. It does not support uploads, live chat, or saving input.

</details>

## Current scope

This project provides **source code for local, single-user deployment**, not a hosted service. Run the backend on loopback with one worker.

- Desktop is supported; accounts, mobile design, and image parsing are not implemented.
- Answers depend on accepted sources. General-knowledge chat with an upload reminder remains planned.
- Saved history does not give the model cross-turn memory. Structural citation checks cannot guarantee semantic correctness.
- Deleting a topic also removes its associated materials, conversations, and progress. Review the confirmation before proceeding.

## Documentation and development

| Learn about | Start here |
| :--- | :--- |
| Installation, testing, and environment limits | [Full deployment guide](docs/local-development.md) |
| Model connection and the FastGPT workflow | [Generation setup](docs/fastgpt-generation.md) |
| Data flow and implementation | [Architecture](docs/architecture.md) |
| Acceptance criteria and measured results | [Evaluation](docs/evaluation.md) · [Public evaluation snapshot](evals/reports/public-p0.md) |
| Keys, source material, and diagnostic data | [Security and data handling](docs/security-and-data.md) |
| Contributing | [Contribution guide](CONTRIBUTING.md) · [Issues](https://github.com/yidi000/grounded-tutor/issues) |

Application code uses the [MIT License](LICENSE). Bundled original sample materials use [CC0](samples/rag-fundamentals/README.md).
