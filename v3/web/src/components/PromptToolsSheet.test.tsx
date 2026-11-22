import {act, cleanup, fireEvent, render, screen, within} from "@testing-library/react";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {PromptToolsSheet, type PromptToolSection} from "./PromptToolsSheet";
import {useState} from "react";

// jsdom does not implement the native dialog top layer. Browser QA covers the
// platform focus trap; this double exposes the lifecycle used by this component.
let dialogMethods: {name: string; descriptor?: PropertyDescriptor}[];
beforeEach(() => {
  dialogMethods = ["showModal", "close"].map(name => ({name, descriptor: Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, name)}));
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {configurable: true, writable: true, value: function (this: HTMLDialogElement) {
    this.open = true;
  }});
  Object.defineProperty(HTMLDialogElement.prototype, "close", {configurable: true, writable: true, value: function (this: HTMLDialogElement) {
    if (!this.open) return;
    this.open = false;
    this.dispatchEvent(new Event("close"));
  }});
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks(); document.body.style.removeProperty("overflow");
  dialogMethods.forEach(({name, descriptor}) => {if (descriptor) Object.defineProperty(HTMLDialogElement.prototype, name, descriptor); else Reflect.deleteProperty(HTMLDialogElement.prototype, name);});
});

function sections(): PromptToolSection[] {
  return [
    {id: "identities", label: "角色与画师", summary: "已选 2 项", content: <input aria-label="未完成的角色名" defaultValue="" />},
    {id: "scene", label: "画面设计", content: <textarea aria-label="画面备注" defaultValue="" />},
    {id: "locks", label: "固定片段", content: <button type="button">添加片段</button>},
  ];
}

it("lets a parent open review and close it on explicit adoption while retaining child input", () => {
  function Controlled() {
    const [open,setOpen]=useState(false);
    return <><button onClick={()=>setOpen(true)}>审阅结果</button><PromptToolsSheet open={open} onOpenChange={setOpen}
      sections={[{id:"review",label:"辅助建议",content:<><input aria-label="编辑建议" defaultValue="原建议"/><button onClick={()=>setOpen(false)}>采用建议</button></>}]}/></>;
  }
  render(<Controlled/>);
  fireEvent.click(screen.getByRole("button",{name:"审阅结果"}));
  const input=screen.getByRole("textbox",{name:"编辑建议"});
  fireEvent.change(input,{target:{value:"手工修改建议"}});
  fireEvent.click(screen.getByRole("button",{name:"采用建议"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"辅助建议"}));
  expect(screen.getByRole("textbox",{name:"编辑建议"})).toBe(input);
  expect(input).toHaveValue("手工修改建议");
  fireEvent.click(screen.getByRole("button",{name:"返回提示词"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("wraps focus between visible first and last controls without reaching the browser chrome", () => {
  vi.spyOn(HTMLElement.prototype,"getClientRects").mockImplementation(function(this:HTMLElement){
    return (this.closest("[hidden]")?[]:[{width:10,height:10}]) as unknown as DOMRectList;
  });
  render(<PromptToolsSheet sections={sections()}/>);
  fireEvent.click(screen.getByRole("button",{name:"画面设计"}));
  const close=screen.getByRole("button",{name:"关闭辅助设置"});
  const back=screen.getByRole("button",{name:"返回提示词"});
  close.focus();fireEvent.keyDown(close,{key:"Tab",shiftKey:true});
  expect(back).toHaveFocus();
  fireEvent.keyDown(back,{key:"Tab"});
  expect(close).toHaveFocus();
});

it("opens the requested named modal with its section and keeps selection status visible", () => {
  render(<PromptToolsSheet sections={sections()} status={<span>2 个 tag 已同步</span>} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText("2 个 tag 已同步")).toBeVisible();
  expect(screen.getByRole("button", {name: /角色与画师.*已选 2 项/})).toBeVisible();
  fireEvent.click(screen.getByRole("button", {name: "画面设计"}));
  const dialog = screen.getByRole("dialog", {name: "创作辅助"});
  expect(dialog).toHaveAttribute("aria-modal", "true");
  expect(within(dialog).getByRole("tab", {name: "画面设计"})).toHaveAttribute("aria-selected", "true");
  expect(within(dialog).getByRole("button", {name: "关闭辅助设置"})).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");
});

it("preserves mounted input drafts while switching panels and closing the Sheet", () => {
  render(<PromptToolsSheet sections={sections()} />);
  const field = screen.getByLabelText("未完成的角色名");
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  fireEvent.change(field, {target: {value: "仍在输入的角色"}});
  fireEvent.click(screen.getByRole("tab", {name: "画面设计"}));
  expect(field.closest("[role=tabpanel]")).toHaveAttribute("hidden");
  expect(screen.queryByRole("textbox", {name: "未完成的角色名"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByLabelText("未完成的角色名")).toBe(field);
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  expect(screen.getByRole("textbox", {name: "未完成的角色名"})).toBe(field);
  expect(field).toHaveValue("仍在输入的角色");
});

it.each(["关闭辅助设置", "返回提示词", "Escape", "native-close", "cancel", "backdrop"])("restores the exact trigger and scroll styles after %s", action => {
  document.body.style.setProperty("overflow", "clip");
  render(<PromptToolsSheet sections={sections()} />);
  const trigger = screen.getByRole("button", {name: "固定片段"});
  trigger.focus();
  const focus = vi.spyOn(trigger, "focus");
  fireEvent.click(trigger);
  const dialog = screen.getByRole("dialog", {name: "创作辅助"}) as HTMLDialogElement;
  if (action === "Escape") fireEvent.keyDown(dialog, {key: "Escape"});
  else if (action === "native-close") act(() => dialog.close());
  else if (action === "cancel") fireEvent(dialog, new Event("cancel", {cancelable: true}));
  else if (action === "backdrop") {
    vi.spyOn(dialog, "getBoundingClientRect").mockReturnValue({left: 500, right: 1260, top: 0, bottom: 1000, width: 760, height: 1000, x: 500, y: 0, toJSON: () => ({})});
    fireEvent.mouseDown(dialog, {clientX: 200, clientY: 100});
    fireEvent.click(dialog, {clientX: 200, clientY: 100});
  } else fireEvent.click(screen.getByRole("button", {name: action}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).toBe("clip");
  expect(focus).toHaveBeenLastCalledWith({preventScroll: true});
  expect(trigger).toHaveFocus();
});

it("disables only content while leaving tabs and closing available", () => {
  const view = render(<PromptToolsSheet sections={sections()} />);
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  view.rerender(<PromptToolsSheet sections={sections()} disabled />);
  expect(screen.getByRole("textbox", {name: "未完成的角色名"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "关闭辅助设置"})).toBeEnabled();
  expect(screen.getByRole("button", {name: "返回提示词"})).toBeEnabled();
  fireEvent.click(screen.getByRole("tab", {name: "固定片段"}));
  expect(screen.getByRole("button", {name: "添加片段"})).toBeDisabled();
  fireEvent.click(screen.getByRole("button", {name: "关闭辅助设置"}));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps consumed or composing Escape inside the Sheet and closes on the next plain Escape", () => {
  render(<PromptToolsSheet sections={[{id: "identity", label: "角色", content: <textarea aria-label="名称" onKeyDown={event => {if (event.key === "Escape" && event.currentTarget.dataset.suggestions === "open") {event.preventDefault(); event.currentTarget.dataset.suggestions = "closed";}}} /> }]} />);
  fireEvent.click(screen.getByRole("button", {name: "角色"}));
  const field = screen.getByRole("textbox", {name: "名称"});
  field.dataset.suggestions = "open";
  fireEvent.keyDown(field, {key: "Escape"});
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.keyDown(field, {key: "Escape", isComposing: true});
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.keyDown(field, {key: "Escape", keyCode: 229});
  expect(screen.getByRole("dialog")).toBeVisible();
  fireEvent.keyDown(field, {key: "Escape"});
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("uses roving tabs with wrapping arrows and Home/End", () => {
  render(<PromptToolsSheet sections={sections()} />);
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  const [identity, scene, locks] = screen.getAllByRole("tab");
  fireEvent.keyDown(identity, {key: "ArrowRight"});
  expect(scene).toHaveFocus();
  expect(scene).toHaveAttribute("aria-selected", "true");
  expect(identity).toHaveAttribute("tabindex", "-1");
  fireEvent.keyDown(scene, {key: "End"});
  expect(locks).toHaveFocus();
  fireEvent.keyDown(locks, {key: "ArrowRight"});
  expect(identity).toHaveFocus();
  fireEvent.keyDown(identity, {key: "ArrowLeft"});
  expect(locks).toHaveFocus();
  fireEvent.keyDown(locks, {key: "Home"});
  expect(identity).toHaveFocus();
  expect(screen.getByRole("tabpanel", {name: /角色与画师/})).toBeVisible();
});

it("opens preferred entries only initially or when their value changes, preserving explicit closes", () => {
  const view = render(<PromptToolsSheet sections={sections()} initialSection="scene" />);
  expect(screen.getByRole("dialog", {name: "创作辅助"})).toBeVisible();
  expect(screen.getByRole("tab", {name: "画面设计"})).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  view.rerender(<PromptToolsSheet sections={sections()} initialSection="scene" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  fireEvent.click(screen.getByRole("tab", {name: "固定片段"}));
  view.rerender(<PromptToolsSheet sections={sections()} initialSection="scene" />);
  expect(screen.getByRole("tab", {name: "固定片段"})).toHaveAttribute("aria-selected", "true");
  fireEvent.click(screen.getByRole("button", {name: "返回提示词"}));
  view.rerender(<PromptToolsSheet sections={sections()} initialSection="identities" />);
  expect(screen.getByRole("dialog", {name: "创作辅助"})).toBeVisible();
  expect(screen.getByRole("tab", {name: /角色与画师/})).toHaveAttribute("aria-selected", "true");
  view.rerender(<PromptToolsSheet sections={sections()} initialSection="" />);
  expect(screen.getByRole("tab", {name: /角色与画师/})).toHaveAttribute("aria-selected", "true");
});

it("releases the open dialog's scroll lock on workspace remount", () => {
  const view = render(<PromptToolsSheet key="first" sections={sections()} />);
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  fireEvent.change(screen.getByRole("textbox", {name: "未完成的角色名"}), {target: {value: "old workspace"}});
  view.rerender(<PromptToolsSheet key="second" sections={sections()} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.style.overflow).not.toBe("hidden");
  fireEvent.click(screen.getByRole("button", {name: /角色与画师/}));
  expect(screen.getByRole("textbox", {name: "未完成的角色名"})).toHaveValue("");
});
