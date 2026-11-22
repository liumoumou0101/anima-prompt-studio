import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { MossNegativePrompt } from "./MossNegativePrompt";

afterEach(cleanup);

it("keeps its entry visible when collapsed and edits the exact controlled text", () => {
  const edited = vi.fn();
  function Harness() {
    const [value, setValue] = useState("");
    const [expanded, setExpanded] = useState(false);
    return <MossNegativePrompt value={value} expanded={expanded} onExpandedChange={setExpanded}
      onChange={next => { edited(next); setValue(next); }} />;
  }
  render(<Harness />);
  const entry = screen.getByText("负向提示词（可选）");
  expect(entry).toBeVisible();
  expect(screen.queryByRole("textbox", { name: "负向提示词" })).toBeNull();
  fireEvent.click(entry);
  const input = screen.getByRole("textbox", { name: "负向提示词" });
  const text = "  水印，\n\n  不要边框  ";
  fireEvent.change(input, { target: { value: text } });
  expect(edited).toHaveBeenLastCalledWith(text);
  expect(input).toHaveValue(text);
  expect(screen.getByText("已填写")).toBeVisible();
  fireEvent.change(input, { target: { value: "" } });
  expect(edited).toHaveBeenLastCalledWith("");
  expect(screen.getByText("未填写")).toBeVisible();
});

it("opens from an external request without losing its draft and respects submission state", () => {
  const change = vi.fn();
  const text = "  多余手指，\n  水印  ";
  const props = { value: text, onChange: change, onExpandedChange: vi.fn() };
  const view = render(<MossNegativePrompt {...props} expanded={false} />);
  expect(screen.queryByRole("textbox", { name: "负向提示词" })).toBeNull();
  view.rerender(<MossNegativePrompt {...props} expanded />);
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toHaveValue(text);
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toHaveFocus();
  view.rerender(<MossNegativePrompt {...props} expanded disabled />);
  expect(screen.getByRole("textbox", { name: "负向提示词" })).toBeDisabled();
  expect(change).not.toHaveBeenCalled();
});
