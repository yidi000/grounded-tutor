import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { LearningWorkspace } from "./learning-workspace";

const wid = "00000000-0000-4000-8000-000000000001";
const idle = { snapshot: { active_mode: "ASK", active_concept_id: null, checkpoint: null, suspended_activity: null }, kind: "idle", checkpoint: null, resume_action: null, concept: null, plan: null, diagnostic: null, lesson: null, check: null };
const invitation = { id: wid, conversation_id: wid, message_id: wid, status: "offered", accept_label: "开始诊断", dismiss_label: "继续提问" };
afterEach(() => vi.unstubAllGlobals());

function mount(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><LearningWorkspace workspaceId={wid} title="Statistics" chatPending={false} retries={new Map()} onSelectCitation={() => undefined} /></QueryClientProvider>);
}
function get(path: string) {
  return path.endsWith("/activity") ? idle : path.endsWith("/invitation") ? invitation : { plans: [] };
}

it("waits for explicit consent and retries a failed start with the same key", async () => {
  const user = userEvent.setup();
  const payloads: object[] = [];
  mount(vi.fn(async (input, init) => {
    if (init?.method === "POST") {
      payloads.push(JSON.parse(String(init.body)));
      if (payloads.length === 1) throw new Error("connection lost");
      return Response.json({ status: "insufficient_material", diagnostic_id: null, questions: [], next_question_id: null });
    }
    return Response.json(get(String(input)));
  }));
  await screen.findByRole("button", { name: "开始诊断" });
  expect(payloads).toHaveLength(0);
  await user.click(screen.getByRole("button", { name: "开始诊断" }));
  await screen.findByRole("alert");
  await user.click(screen.getByRole("button", { name: "开始诊断" }));
  await screen.findByText("当前资料不足以生成这一步，请补充或复核资料后再试。");
  expect(payloads).toHaveLength(2);
  expect(payloads[1]).toEqual(payloads[0]);
  expect(payloads[0]).toMatchObject({ consent: true, invitation_id: wid });
});

it("shows a recoverable error when the invitation cannot be loaded", async () => {
  mount(vi.fn(async (input) => {
    if (String(input).endsWith("/invitation")) throw new Error("offline");
    return Response.json(get(String(input)));
  }));
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("暂时无法读取学习信息"));
});
