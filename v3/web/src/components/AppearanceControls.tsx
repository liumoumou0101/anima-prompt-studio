import {Moon, Sun} from "@phosphor-icons/react";
import {useId} from "react";
import {useAppearance, type AppearanceTheme} from "../lib/appearance";

export function AppearanceControls({compact = false}: {compact?: boolean}) {
  const {theme, resolvedTheme, setTheme} = useAppearance();
  const id = useId();
  return <div className={`appearance-controls${compact ? " appearance-controls--compact" : ""}`} role="group" aria-label="界面外观">
    <label htmlFor={`${id}-theme`}><span>{resolvedTheme === "dark" ? <Moon size={16} aria-hidden="true" /> : <Sun size={16} aria-hidden="true" />}明暗主题</span>
      <select id={`${id}-theme`} value={theme} onChange={event => setTheme(event.target.value as AppearanceTheme)}>
        <option value="light">浅色</option><option value="dark">夜间</option><option value="system">跟随系统</option>
      </select>
    </label>
  </div>;
}
