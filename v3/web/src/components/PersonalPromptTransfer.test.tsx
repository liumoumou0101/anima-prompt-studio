import {render, screen} from "@testing-library/react";
import {expect, it} from "vitest";
import {PersonalPromptTransfer} from "./PersonalPromptTransfer";

it.each(["positive", "negative"] as const)("permits exactly 20000 appended %s code points and blocks overflow", side => {
  const raw = "😀".repeat(19_998);
  const props = {
    addition: {positive: "", negative: "", [side]: raw}, before: {positive: "x", negative: "x"},
    receipt: null, blockedReason: "", needsRefresh: false, undoChanged: false, busy: false,
    onConfirm: () => {}, onCancel: () => {}, onRefresh: () => {}, onUndo: () => {},
  };
  const {rerender} = render(<PersonalPromptTransfer {...props} />);
  expect(screen.getByRole("textbox", {name: `追加后${side === "positive" ? "正向" : "负向"}提示词`}))
    .toHaveValue("x\n" + raw);
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeEnabled();
  rerender(<PersonalPromptTransfer {...props} addition={{...props.addition, [side]: raw + "😀"}} />);
  expect(screen.getByRole("button", {name: "确认追加原文"})).toBeDisabled();
  expect(screen.getByText(/超过 20,000 字符/)).toBeInTheDocument();
});
