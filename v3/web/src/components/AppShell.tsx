import {NavLink, Outlet, useLocation} from "react-router-dom";
import {ChatCircleDots, GearSix, Hash, Images, ImageSquare, PaintBrush, TextAlignLeft, FlowArrow, DotsThree, CaretDown, Leaf} from "@phosphor-icons/react";
import type {BootstrapResponse} from "../lib/types";
import {useAppearance} from "../lib/appearance";
import {AppearanceControls} from "./AppearanceControls";

const primaryNav = [
  {to: "/workbench", icon: ChatCircleDots, label: "工作台"},
  {to: "/references", icon: Images, label: "参考案例"},
  {to: "/artists", icon: PaintBrush, label: "画师"},
  {to: "/tags", icon: Hash, label: "标签"},
  {to: "/gallery", icon: Images, label: "画廊"},
];
const toolNav = [
  {to: "/direct", icon: TextAlignLeft, label: "英文直出"},
  {to: "/generate", icon: ImageSquare, label: "生成"},
  {to: "/workflows", icon: FlowArrow, label: "工作流"},
];

export function AppShell({bootstrap}: {bootstrap: BootstrapResponse}) {
  const {layout} = useAppearance();
  const location = useLocation();
  const isToolActive = toolNav.some(item => location.pathname.startsWith(item.to));
  return (
    <div className="app-shell">
      <a className="skip-to-content" href="#main-content">跳到内容</a>
      <aside className="sidebar">
        <div className="brand" aria-label="ANIMA Prompt Studio">
          <span className="brand-mark" aria-hidden="true"><Leaf size={28} weight="duotone" /></span>
          <span className="brand-copy"><strong>ANIMA</strong><small>{layout === "editorial" ? "提示词编辑台" : "Prompt Studio"}</small></span>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          {primaryNav.map(item => <NavLink key={item.to} to={item.to} aria-label={item.label} title={item.label} className={({isActive}) => `nav-item${isActive ? " is-active" : ""}`}>
            <span className="nav-glyph" aria-hidden="true"><item.icon size={20} /></span><span>{item.label}</span>
          </NavLink>)}
          <details className={`nav-more${isToolActive ? " has-active-route" : ""}`}>
            <summary className="nav-item"><span className="nav-glyph" aria-hidden="true"><DotsThree size={22} /></span><span>更多工具</span><CaretDown size={13} aria-hidden="true" /></summary>
            <div className="nav-more-items">
              {toolNav.map(item => <NavLink key={item.to} to={item.to} aria-label={item.label} className={({isActive}) => `nav-item${isActive ? " is-active" : ""}`} onClick={event => event.currentTarget.closest("details")?.removeAttribute("open")}>
                <span className="nav-glyph" aria-hidden="true"><item.icon size={19} /></span><span>{item.label}</span>
              </NavLink>)}
            </div>
          </details>
        </nav>
        <div className="shell-appearance"><AppearanceControls compact /></div>
        <NavLink to="/settings" className={({isActive}) => `nav-item nav-item--settings${isActive ? " is-active" : ""}`} aria-label="设置">
          <span className="nav-glyph" aria-hidden="true"><GearSix size={20} /></span><span>设置</span>
        </NavLink>
        <div className="sidebar-status" title={bootstrap.data_pack.id || "未安装本地数据包"}>
          <span className={`status-dot${bootstrap.data_pack.ready ? " is-ready" : ""}`} />
          <div><strong>{bootstrap.data_pack.ready ? "本地资料就绪" : "缺少数据包"}</strong><small>V3 · {bootstrap.app_version}</small></div>
        </div>
      </aside>
      {/* Keep this outlet mounted in the same position across all appearances. */}
      <main className="main-stage" id="main-content" tabIndex={-1}><Outlet /></main>
    </div>
  );
}
