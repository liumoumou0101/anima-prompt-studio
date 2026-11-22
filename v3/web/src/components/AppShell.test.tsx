import {useEffect, useState} from "react";
import {fireEvent, render, screen} from "@testing-library/react";
import {MemoryRouter, Route, Routes} from "react-router-dom";
import {describe, expect, it, vi} from "vitest";
import {AppShell} from "./AppShell";
import {AppearanceControls} from "./AppearanceControls";
import type {BootstrapResponse} from "../lib/types";

const bootstrap: BootstrapResponse = {app_version: "test", api_version: "3", data_pack: {ready: true, id: "test-pack", cutoff_mode: "exact"}, features: {}, model_profiles: [], settings_summary: {}};

describe("shared appearance shell", () => {
  it("keeps the route, draft, image and operation mounted across themes and navigation sizes", () => {
    const mounted = vi.fn(); const unmounted = vi.fn();
    function Draft() {
      const [text, setText] = useState("");
      const [busy, setBusy] = useState(false);
      useEffect(() => {mounted(); return unmounted;}, []);
      return <div><textarea aria-label="未发送想法" value={text} onChange={e => setText(e.target.value)} /><button onClick={() => setBusy(true)}>开始本地操作</button><span>{busy ? "进行中" : "空闲"}</span><img alt="原图" src="/original.png" /></div>;
    }
    render(<MemoryRouter initialEntries={['/workbench']}><Routes><Route element={<AppShell bootstrap={bootstrap} />}><Route path="workbench" element={<Draft />} /></Route></Routes></MemoryRouter>);
    const draft = screen.getByLabelText("未发送想法"); const picture = screen.getByAltText("原图");
    fireEvent.change(draft, {target: {value: "原提示词、角色和未发送修改"}});
    fireEvent.click(screen.getByText("开始本地操作"));
    expect(screen.queryByLabelText("界面布局")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", {name: "展开导航"}));
    for (const theme of ['light', 'dark', 'system']) {
      fireEvent.change(screen.getByLabelText("明暗主题"), {target: {value: theme}});
      expect(document.documentElement.dataset.layout).toBe("unified");
      expect(screen.getByLabelText("未发送想法")).toBe(draft);
      expect(draft).toHaveValue("原提示词、角色和未发送修改");
      expect(screen.getByAltText("原图")).toBe(picture);
      expect(screen.getByText("进行中")).toBeInTheDocument();
    }
    expect(mounted).toHaveBeenCalledOnce(); expect(unmounted).not.toHaveBeenCalled();
    expect(picture).toHaveAttribute("src", "/original.png");
  });
  it("keeps every prior route available and shares controls without a provider", () => {
    render(<MemoryRouter><Routes><Route path="*" element={<AppShell bootstrap={bootstrap} />} /></Routes><section aria-label="设置外观"><AppearanceControls /></section></MemoryRouter>);
    fireEvent.click(screen.getByText("更多工具"));
    for (const label of ["工作台", "参考案例", "画师", "标签", "个人标签超市", "画廊", "英文直出", "生成", "工作流", "设置"]) expect(screen.getByRole("link", {name: label})).toBeInTheDocument();
    const themes = screen.getAllByLabelText("明暗主题");
    fireEvent.change(themes[0], {target: {value: "light"}});
    expect(screen.queryByLabelText("界面布局")).not.toBeInTheDocument(); expect(themes[1]).toHaveValue("light");
  });
});
