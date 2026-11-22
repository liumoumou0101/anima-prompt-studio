import {cleanup, fireEvent, render, screen} from "@testing-library/react";
import {afterEach, expect, it} from "vitest";
import {useState} from "react";
import {ConversationStudioView} from "./ConversationStudioView";

afterEach(cleanup);

function Harness() {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeView, setActiveView] = useState<"prompt" | "images">("images");
  return <><button onClick={() => setHistoryOpen(true)}>打开记录</button>
    <button onClick={() => setActiveView("prompt")}>更新完成</button>
    <ConversationStudioView editor={<textarea aria-label="当前提示词" defaultValue="red coat" />}
      results={<p>当前图片</p>} settings={<select aria-label="模型"><option>Turbo</option></select>}
      composer={<textarea aria-label="修改意见" />} auxiliary={<p>高级画面设置</p>}
      history={<p>外套改成红色</p>} historyOpen={historyOpen} onCloseHistory={() => setHistoryOpen(false)}
      onOpenHistory={() => setHistoryOpen(true)}
      activeView={activeView} />
  </>;
}

it("preserves an edited prompt when switching compact views and follows completed actions", () => {
  render(<Harness />);
  const prompt = screen.getByRole("textbox", {name: "当前提示词"});
  fireEvent.change(prompt, {target: {value: "blue coat"}});
  // jsdom does not apply viewport media queries; these compact controls stay mounted.
  const promptTab = screen.getByRole("button", {name: "提示词", hidden: true});
  const imageTab = screen.getByRole("button", {name: "图片预览", hidden: true});
  expect(imageTab).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(promptTab);
  expect(promptTab).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(imageTab);
  expect(prompt).toHaveValue("blue coat");
  fireEvent.click(screen.getByRole("button", {name: "更新完成"}));
  expect(promptTab).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("textbox", {name: "修改意见"})).toBeInTheDocument();
});

it("opens parameters and versions alongside the same editor without a covering dock", () => {
  render(<Harness />);
  const prompt = screen.getByRole("textbox", {name: "当前提示词"});
  fireEvent.change(prompt, {target: {value: "keep this draft"}});
  fireEvent.click(screen.getByRole("button", {name: "生成参数"}));
  expect(screen.getByRole("region", {name: "生成参数"})).toBeVisible();
  expect(screen.getByRole("combobox", {name: "模型"})).toBeVisible();
  fireEvent.click(screen.getByRole("button", {name: "创作记录"}));
  expect(screen.getByRole("dialog", {name: "创作记录"})).toHaveAttribute("aria-modal", "false");
  expect(prompt).toHaveValue("keep this draft");
  expect(screen.getByRole("textbox", {name: "当前提示词"})).toBe(prompt);
  expect(document.body.style.overflow).not.toBe("hidden");
});

it("opens creative history as a named dialog and closes with the close action or Escape", () => {
  render(<Harness />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "打开记录"}));
  expect(screen.getByRole("dialog", {name: "创作记录"})).toBeInTheDocument();
  expect(screen.getByText("外套改成红色")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "关闭创作记录"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "打开记录"}));
  fireEvent.keyDown(screen.getByRole("dialog", {name: "创作记录"}), {key: "Escape"});
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows a newly accepted result after editing parameters without remounting the editor", () => {
  const props={editor:<textarea aria-label="当前提示词" defaultValue="draft" />,results:<p>新任务进度</p>,settings:<p>采样条件</p>,composer:null,historyOpen:false,onCloseHistory:()=>{}};
  const {rerender}=render(<ConversationStudioView {...props} />);
  const editor=screen.getByRole("textbox",{name:"当前提示词"});
  fireEvent.change(editor,{target:{value:"keep editing"}});
  fireEvent.click(screen.getByRole("button",{name:"生成参数"}));
  expect(screen.getByRole("region",{name:"生成参数"})).toBeVisible();
  rerender(<ConversationStudioView {...props} resultRequestKey="accepted-run-2" />);
  expect(screen.getByRole("region",{name:"生成结果"})).toBeVisible();
  expect(screen.getByRole("textbox",{name:"当前提示词"})).toBe(editor);
  expect(editor).toHaveValue("keep editing");
});
