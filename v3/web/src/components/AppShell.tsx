import {NavLink, Outlet} from "react-router-dom";
import {ChatCircleDots, GearSix, Hash, Images, ImageSquare, PaintBrush, TextAlignLeft, FlowArrow} from "@phosphor-icons/react";
import type {BootstrapResponse} from "../lib/types";

const nav = [
  {to: "/workbench", icon: ChatCircleDots, label: "工作台", enabled: true},
  {to: "/direct", icon: TextAlignLeft, label: "英文直出", enabled: true},
  {to: "/tags", icon: Hash, label: "标签", enabled: true},
  {to: "/artists", icon: PaintBrush, label: "画师", enabled: true},
  {to: "/generate", icon: ImageSquare, label: "生成", enabled: true},
  {to: "/gallery", icon: Images, label: "画廊", enabled: true},
  {to: "/workflows", icon: FlowArrow, label: "工作流", enabled: true},
  {to: "/references", icon: Images, label: "参考案例", enabled: true},
];

export function AppShell({bootstrap}: {bootstrap: BootstrapResponse}) {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand" aria-label="ANIMA Prompt Studio">
          <span className="brand-mark">A</span>
          <span className="brand-copy"><strong>ANIMA</strong><small>Prompt Studio</small></span>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          {nav.map((item) => item.enabled ? (
            <NavLink key={item.to} to={item.to} aria-label={item.label} title={item.label} className={({isActive}) => `nav-item${isActive ? " is-active" : ""}`}>
              <span className="nav-glyph" aria-hidden="true"><item.icon size={19} /></span><span>{item.label}</span>
            </NavLink>
          ) : (
            <span key={item.to} className="nav-item is-disabled" title="后续阶段开放">
              <span className="nav-glyph" aria-hidden="true"><item.icon size={19} /></span><span>{item.label}</span><i>soon</i>
            </span>
          ))}
        </nav>
        <NavLink to="/settings" className={({isActive}) => `nav-item nav-item--settings${isActive ? " is-active" : ""}`} aria-label="设置">
          <span className="nav-glyph" aria-hidden="true"><GearSix size={19} /></span><span>设置</span>
        </NavLink>
        <div className="sidebar-status">
          <span className={`status-dot${bootstrap.data_pack.ready ? " is-ready" : ""}`} />
          <div><strong>{bootstrap.data_pack.ready ? "本地数据就绪" : "缺少数据包"}</strong><small>{bootstrap.data_pack.id || "未安装"}</small></div>
        </div>
        <div className="sidebar-meta">V3 · {bootstrap.app_version}</div>
      </aside>
      <main className="main-stage"><Outlet /></main>
    </div>
  );
}
