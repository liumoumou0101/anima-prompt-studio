import {useState} from "react";
import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it} from "vitest";
import type {PromptLock} from "../lib/conversation";
import {PromptLocks} from "./PromptLocks";

afterEach(cleanup);
function Harness() {
  const [locks, setLocks] = useState<PromptLock[]>([]);
  return <><PromptLocks positive="short black hair, blue coat" negative="extra fingers" locks={locks} onChange={setLocks} />
    <output aria-label="saved rules">{JSON.stringify(locks)}</output></>;
}
it("lets the user protect identity independently and remove the rule", () => {
  render(<Harness />);
  fireEvent.click(screen.getByText(/固定提示词片段/, {selector:"summary"}));
  fireEvent.change(screen.getByLabelText("要固定的原文片段"), {target:{value:"short black hair"}});
  fireEvent.click(screen.getByRole("button", {name:"固定片段"}));
  expect(screen.getByLabelText("saved rules")).toHaveTextContent('[{"target":"positive","text":"short black hair"}]');
  fireEvent.click(screen.getByRole("button", {name:"解除固定：short black hair"}));
  expect(screen.getByLabelText("saved rules")).toHaveTextContent("[]");
});
it("does not accept missing text or text present only in the other prompt", () => {
  render(<Harness />);
  fireEvent.click(screen.getByText(/固定提示词片段/, {selector:"summary"}));
  fireEvent.change(screen.getByLabelText("要固定的原文片段"), {target:{value:"extra fingers"}});
  expect(screen.getByRole("button",{name:"固定片段"})).toBeDisabled();
  fireEvent.change(screen.getByLabelText("片段所在提示词"), {target:{value:"negative"}});
  fireEvent.click(screen.getByRole("button",{name:"固定片段"}));
  expect(screen.getByLabelText("saved rules")).toHaveTextContent('[{"target":"negative","text":"extra fingers"}]');
});
