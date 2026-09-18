import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {useState} from "react";
import {ConversationVersions} from "./ConversationVersions";
import {emptyRequirements, type ConversationRecord} from "../lib/conversation";

const current: ConversationRecord = {id: "workspace_versions", title: "当前创作", revision: 3,
  created_at: "2026-09-18", updated_at: "2026-09-18", draft: {
    positive_text: "", excluded_text: "", model_profile: "anima_base_v1", mode: "faithful",
    requirements: {...emptyRequirements(), contract: "anima-requirements/1", revision: 1},
    compiled: {positive: "red coat", negative: "", compiled_token: "cmp_3", source: "llm"},
    compile_state: "fresh", conversation_events: []}};

beforeEach(() => {
  sessionStorage.setItem("anima-v3-session", "test");
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({items: [current,
    {...current, revision: 2, draft: {...current.draft, compiled: {...current.draft.compiled!, positive: "blue coat"}}}]})));
});
afterEach(() => {cleanup(); vi.restoreAllMocks();});

function Harness({disabled = false}: {disabled?: boolean}) {
  const [chosen, setChosen] = useState<number | null>(null);
  return <><ConversationVersions record={current} disabled={disabled} onRestore={() => {}}
    onFork={setChosen} />{chosen !== null && <output>创建自版本 {chosen}</output>}</>;
}

it("branches a selected historical version without invoking restore", async () => {
  render(<Harness />);
  fireEvent.click(screen.getByText(/版本历史 · 当前版本/, {selector: "summary"}));
  fireEvent.click(await screen.findByRole("button", {name: "从版本 2 另开会话"}));
  expect(screen.getByText("创建自版本 2")).toBeInTheDocument();
  expect(screen.getByText("版本 3 · 当前")).toBeInTheDocument();
});

it("permits branching the current saved version while its restore is disabled", async () => {
  render(<Harness />);
  fireEvent.click(screen.getByText(/版本历史 · 当前版本/, {selector: "summary"}));
  const button = await screen.findByRole("button", {name: "从版本 3 另开会话"});
  expect(screen.getByRole("button", {name: "恢复版本 3"})).toBeDisabled();
  fireEvent.click(button);
  expect(screen.getByText("创建自版本 3")).toBeInTheDocument();
});

it("prevents branching while the caller is protecting unsaved or pending work", async () => {
  render(<Harness disabled />);
  fireEvent.click(screen.getByText(/版本历史 · 当前版本/, {selector: "summary"}));
  await waitFor(() => expect(screen.getByRole("button", {name: "从版本 2 另开会话"})).toBeDisabled());
  expect(screen.getByRole("button", {name: "从版本 3 另开会话"})).toBeDisabled();
});
