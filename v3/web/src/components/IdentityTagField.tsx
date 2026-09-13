import {useEffect, useId, useRef, useState} from "react";
import {apiRequest} from "../lib/api";
import {normalizeIdentityTags} from "../lib/conversation";

export type IdentityKind = "character" | "series" | "artist";
export type IdentitySuggestion = {
  name: string; render_name: string; cn_name: string | null; kind: IdentityKind;
  favorite: boolean; match_kind?: string; match_text?: string; match_source?: string;
  user_aliases: string[]; related_series: {name: string; cn_name: string | null; render_name: string; cooc_count: number}[];
  knowledge: {status: "unknown"; model_profile_id: string | null; reason: string};
};
type Preferences = {recent: IdentitySuggestion[]; favorites: IdentitySuggestion[];
  aliases: {alias: string; name: string; normalized_alias: string}[]};
const emptyPreferences: Preferences = {recent: [], favorites: [], aliases: []};
const kindNames: Record<IdentityKind, string> = {character: "角色", series: "作品", artist: "画师"};
const matchNames: Record<string, string> = {canonical: "标准 tag", render_name: "正式名称", cn_name: "中文名称",
  alias: "词库别名", user_alias: "我的别名", related_term: "关联词匹配", name_contains: "名称包含", custom: "自由 tag"};
function errorText(error: unknown) {return error instanceof Error ? error.message : "暂时无法读取补全，仍可自由输入。";}

export function IdentityTagField({kind, label, placeholder, values, onChange, onPick, modelProfileId, compact = false}: {
  kind: IdentityKind; label: string; placeholder: string; values: string[]; onChange: (values: string[]) => void;
  onPick?: (item: IdentitySuggestion) => void; modelProfileId?: string; compact?: boolean;
}) {
  const inputId = useId();
  const listId = `${inputId}-list`;
  const field = useRef<HTMLTextAreaElement>(null);
  const composing = useRef(false);
  const queryEpoch = useRef(0);
  const line = useRef(0);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<IdentitySuggestion[]>([]);
  const [active, setActive] = useState(-1);
  const [preferences, setPreferences] = useState<Preferences>(emptyPreferences);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [compositionVersion, setCompositionVersion] = useState(0);
  const [aliasesOpen, setAliasesOpen] = useState(false);
  const [aliasName, setAliasName] = useState("");
  const [aliasText, setAliasText] = useState("");
  const [allFavorites, setAllFavorites] = useState(false);
  const kindName = kindNames[kind];
  const normalized = normalizeIdentityTags(values, kind === "artist");
  const hasValues = normalized.length > 0;
  const modelQuery = modelProfileId ? `&model_profile_id=${encodeURIComponent(modelProfileId)}` : "";

  async function loadPreferences(signal?: AbortSignal) {
    const result = await apiRequest<Preferences>(`/api/v3/identities/preferences?kind=${kind}${modelQuery}`, {signal});
    if (!signal?.aborted) setPreferences({
      recent: Array.isArray(result.recent) ? result.recent : [],
      favorites: Array.isArray(result.favorites) ? result.favorites : [],
      aliases: Array.isArray(result.aliases) ? result.aliases : [],
    });
  }
  useEffect(() => {
    if (!open && !aliasesOpen && !hasValues) return;
    const controller = new AbortController();
    void loadPreferences(controller.signal).catch(error => {if (!controller.signal.aborted) setError(errorText(error));});
    return () => controller.abort();
  }, [open, aliasesOpen, hasValues, kind, modelProfileId]);
  useEffect(() => {
    const epoch = ++queryEpoch.current;
    setItems([]); setActive(-1); setLoading(false);
    if (!open || !query.trim() || composing.current) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      void apiRequest<{items: IdentitySuggestion[]}>(`/api/v3/identities/search?kind=${kind}&q=${encodeURIComponent(query.trim())}${modelQuery}`,
        {signal: controller.signal}).then(result => {
          if (controller.signal.aborted || epoch !== queryEpoch.current) return;
          setItems(Array.isArray(result.items) ? result.items : []); setActive(-1); setError("");
        }).catch(error => {if (!controller.signal.aborted && epoch === queryEpoch.current) setError(errorText(error));})
        .finally(() => {if (!controller.signal.aborted && epoch === queryEpoch.current) setLoading(false);});
    }, 250);
    return () => {window.clearTimeout(timer); controller.abort();};
  }, [query, open, kind, modelProfileId, compositionVersion]);

  function updateQuery(value: string, caret: number) {
    line.current = value.slice(0, caret).split("\n").length - 1;
    setQuery(value.split("\n")[line.current] || "");
    setOpen(true);
  }
  function recordUsed(names: string[]) {
    void apiRequest("/api/v3/identities/used", {method: "POST", body: JSON.stringify({kind, names})})
      .then(() => loadPreferences()).catch(error => setError(errorText(error)));
  }
  function choose(item: IdentitySuggestion, append = false) {
    const next = [...values];
    if (append) next.push(item.name);
    else next.splice(line.current, 1, item.name);
    onChange([...new Set(next.filter(value => value.trim()))]);
    setOpen(false); setQuery(""); setItems([]); setActive(-1);
    recordUsed([item.name]); onPick?.(item);
  }
  async function toggleFavorite(name: string, enabled: boolean) {
    try {
      await apiRequest("/api/v3/identities/favorite", {method: "PUT", body: JSON.stringify({kind, name, enabled})});
      await loadPreferences();
      setItems(items => items.map(item => item.name === name ? {...item, favorite: enabled} : item));
      setError("");
    } catch (error) {setError(errorText(error));}
  }
  async function saveAlias() {
    try {
      await apiRequest("/api/v3/identities/alias", {method: "PUT", body: JSON.stringify({kind, name: aliasName, alias: aliasText})});
      await loadPreferences(); setAliasText(""); setError("");
    } catch (error) {setError(errorText(error));}
  }
  async function deleteAlias(alias: string) {
    try {
      await apiRequest("/api/v3/identities/alias", {method: "DELETE", body: JSON.stringify({kind, alias})});
      await loadPreferences(); setError("");
    } catch (error) {setError(errorText(error));}
  }
  return <div className={`identity-tag-field${compact ? " identity-tag-field--compact" : ""}`}>
    <label htmlFor={inputId}>{compact ? kindName : label}</label>
    <textarea ref={field} id={inputId} rows={compact ? Math.min(3, Math.max(1, values.length)) : 2}
      aria-label={compact ? label : undefined} role="combobox" aria-autocomplete="list" aria-expanded={open}
      aria-controls={listId} aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
      value={values.join("\n")} placeholder={placeholder}
      onFocus={event => updateQuery(event.currentTarget.value, event.currentTarget.selectionStart)}
      onClick={event => updateQuery(event.currentTarget.value, event.currentTarget.selectionStart)}
      onChange={event => {onChange(event.target.value.split("\n")); updateQuery(event.target.value, event.target.selectionStart);}}
      onCompositionStart={() => {composing.current = true; ++queryEpoch.current; setItems([]); setActive(-1);}}
      onCompositionEnd={event => {composing.current = false; setCompositionVersion(value => value + 1); updateQuery(event.currentTarget.value, event.currentTarget.selectionStart);}}
      onPaste={event => {
        const pasted = event.clipboardData.getData("text");
        if (!/[\n\r,，;；]/.test(pasted)) return;
        event.preventDefault();
        const target = event.currentTarget;
        const insertion = pasted.split(/[\n\r,，;；]+/).map(value => value.trim()).filter(Boolean).join("\n");
        const next = target.value.slice(0, target.selectionStart) + insertion + target.value.slice(target.selectionEnd);
        onChange(next.split("\n")); setOpen(false); setQuery("");
      }}
      onKeyDown={event => {
        if (composing.current || event.nativeEvent.isComposing || event.keyCode === 229) return;
        if (event.key === "Escape") {event.preventDefault(); setOpen(false); return;}
        if (!open || !items.length) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault(); setActive(value => event.key === "ArrowDown" ? (value + 1) % items.length : (value <= 0 ? items.length - 1 : value - 1));
        } else if (event.key === "Enter" && active >= 0) {event.preventDefault(); choose(items[active]);}
      }}
      onBlur={event => {
        // Mouse selection is kept inside the field by the suggestion mousedown handler.
        if (!event.relatedTarget || !event.currentTarget.parentElement?.contains(event.relatedTarget as Node)) setOpen(false);
        const tags = normalizeIdentityTags(values, kind === "artist");
        if (tags.length) recordUsed(tags.slice(0, 50));
      }} />
    {open && <div className="identity-tag-suggestions">
      {loading && <p role="status">正在查找{kindName}…</p>}
      <ul id={listId} role="listbox" aria-label={`${kindName}补全候选`}>
        {items.map((item, index) => <li id={`${listId}-${index}`} key={item.name} role="option" aria-selected={index === active}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(item)}>
          <button type="button" tabIndex={-1}>{item.cn_name || item.render_name} · {item.name}</button>
          <small> {matchNames[item.match_kind || ""] || "词库名称"}{item.match_kind === "user_alias" ? `：${item.match_text}` : ""}</small>
        </li>)}
      </ul>
      {!loading && query.trim() && !items.length && !error && <p className="conversation-muted">没有找到名称，可保留为自由 tag，或在下方登记自己的别名。</p>}
      {preferences.favorites.length > 0 && <div className="identity-tag-history">收藏：{(allFavorites ? preferences.favorites : preferences.favorites.slice(0, 8)).map(item => <button key={item.name} type="button"
        onMouseDown={event => event.preventDefault()} onClick={() => choose(item, true)}>{item.cn_name || item.render_name}</button>)}
        {preferences.favorites.length > 8 && <button type="button" onMouseDown={event => event.preventDefault()}
          onClick={() => setAllFavorites(value => !value)}>{allFavorites ? "收起收藏" : `显示全部 ${preferences.favorites.length} 个收藏`}</button>}</div>}
      {preferences.recent.length > 0 && <div className="identity-tag-history">最近使用：{preferences.recent.slice(0, 8).map(item => <button key={item.name} type="button"
        onMouseDown={event => event.preventDefault()} onClick={() => choose(item, true)}>{item.cn_name || item.render_name}</button>)}</div>}
    </div>}
    {normalized.length > 0 && <ul className="identity-tag-selected" aria-label={`已添加${kindName} tag`}>
      {normalized.map(name => {
        const canonical = name.replaceAll(" ", "_");
        const favorite = preferences.favorites.some(item => item.name === canonical);
        return <li key={name}><span>{kind === "artist" ? "@" : ""}{name}</span> <button type="button" aria-label={`移除${kindName} ${name}`}
          onClick={() => onChange(values.filter(value => normalizeIdentityTags([value], kind === "artist")[0] !== name))}>移除</button>{" "}
          <button type="button" aria-label={`${favorite ? "取消收藏" : "收藏"}${kindName} ${name}`} aria-pressed={favorite}
            onClick={() => void toggleFavorite(canonical, !favorite)}>{favorite ? "已收藏" : "收藏"}</button></li>;
      })}
    </ul>}
    <button type="button" className="identity-tag-alias-toggle" aria-label={compact ? `管理${kindName}别名` : undefined}
      title={compact ? `管理${kindName}别名` : undefined} aria-expanded={aliasesOpen}
      onClick={() => setAliasesOpen(value => !value)}>{compact ? "⋯" : `管理${kindName}别名`}</button>
    {aliasesOpen && <div className="identity-tag-aliases">
      <p className="conversation-muted">用户别名只帮助本机搜索；生成时仍使用你指定的标准 tag，不代表模型认识这个名称。</p>
      <label>{kindName}标准 tag<input value={aliasName} onChange={event => setAliasName(event.target.value)} /></label>
      <label>{kindName}自定义别名<input value={aliasText} onChange={event => setAliasText(event.target.value)} placeholder="中文、日文或你习惯的叫法" /></label>
      <button type="button" disabled={!aliasName.trim() || !aliasText.trim()} onClick={() => void saveAlias()}>保存{kindName}别名</button>
      <ul>{preferences.aliases.map(item => <li key={item.normalized_alias}>{item.alias} → {item.name}（用户添加）{" "}
        <button type="button" onClick={() => void deleteAlias(item.alias)} aria-label={`删除别名 ${item.alias}`}>删除</button></li>)}</ul>
    </div>}
    {error && <p className="identity-tag-error" role="status">{error} 自由输入仍会保留。</p>}
  </div>;
}
