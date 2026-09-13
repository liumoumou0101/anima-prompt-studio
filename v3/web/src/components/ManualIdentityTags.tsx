import {normalizeIdentityTags} from "../lib/conversation";
import {useState} from "react";
import {IdentityTagField, type IdentitySuggestion} from "./IdentityTagField";
import "./manualIdentityTags.css";

export function ManualIdentityTags({characters, series, artists, onCharacters, onSeries, onArtists, modelProfileId, compact = false}: {
  characters: string[]; series: string[]; artists: string[];
  onCharacters: (tags: string[]) => void; onSeries: (tags: string[]) => void; onArtists: (tags: string[]) => void;
  modelProfileId?: string;
  compact?: boolean;
}) {
  const [relatedCharacter, setRelatedCharacter] = useState<IdentitySuggestion | null>(null);
  const tagCount = normalizeIdentityTags(characters).length + normalizeIdentityTags(series).length + normalizeIdentityTags(artists, true).length;
  // The workbench keys this component by record, so only a new record resets this preference.
  const [compactOpen, setCompactOpen] = useState(() => tagCount > 0);
  const preview = [...normalizeIdentityTags(characters), ...normalizeIdentityTags(series),
    ...normalizeIdentityTags(artists, true).map(tag => `@${tag}`)].map(tag => tag.replace(/[()]/g, "\\$&")).join(", ");
  const help = <>
    <p className="conversation-muted">填写模型认识的英文 tag，每行一个；无需在本地词库中存在。动画、游戏角色填在角色栏，作品名填在作品栏。这里只指定已有知识，不会训练新角色。</p>
    <p className="conversation-muted">输入名称可补全，↑↓ 选择、Enter 确认、Esc 关闭；支持多行或逗号分隔粘贴。词库收录不等于当前模型已学会，具体角色与画师的模型知识尚未逐项验证。</p>
  </>;
  const normalizationHelp = <p className="conversation-muted">保存并编译时转为小写、下划线转空格，画师自动加 @。名称中的括号按文字保留，不作为权重。多角色的位置、动作和各自外观仍在主体要求中描述。</p>;
  const fields = <div className="manual-identity-grid">
    <div className="manual-identity-group">
    <IdentityTagField kind="character" label="角色 tag（每行一个）" values={characters} onChange={onCharacters} onPick={setRelatedCharacter}
      placeholder={compact ? "输入角色名或 tag" : "例如：oomuro_sakurako，也可搜索中文名"} modelProfileId={modelProfileId} compact={compact} />
    {relatedCharacter && relatedCharacter.related_series.length > 0 && normalizeIdentityTags(characters).includes(normalizeIdentityTags([relatedCharacter.name])[0]) && <div className="manual-identity-related">
      <p className="conversation-muted">{relatedCharacter.cn_name || relatedCharacter.render_name} 的共现作品（可能包含联动，请确认后添加）：</p>
      {relatedCharacter.related_series.filter(item => !normalizeIdentityTags(series).includes(normalizeIdentityTags([item.name])[0])).map(item =>
        <button type="button" key={item.name} onClick={() => onSeries([...series, item.name])}>添加作品：{item.cn_name || item.render_name} · {item.name}</button>)}
      <button type="button" onClick={() => setRelatedCharacter(null)}>忽略作品建议</button>
    </div>}
    </div>
    <div className="manual-identity-group">
    <IdentityTagField kind="series" label="作品 tag（动画／游戏，每行一个）" values={series} onChange={onSeries}
      placeholder={compact ? "输入作品名或 tag" : "例如：yuru_yuri"} modelProfileId={modelProfileId} compact={compact} />
    </div>
    <div className="manual-identity-group">
    <IdentityTagField kind="artist" label="画师 tag（每行一个，可带 @）" values={artists} onChange={onArtists}
      placeholder={compact ? "输入画师名或 @tag" : "例如：@nnn_yryr"} modelProfileId={modelProfileId} compact={compact} />
    </div>
  </div>;
  const tagPreview = <output aria-label="手动 tag 预览">{preview || "尚未添加手动 tag"}</output>;
  const updateHint = <p className="conversation-muted">这些 tag 会写入可编辑的正向提示词，不会自动出图。要更换或移除固定 tag，请修改本栏后重新编译。</p>;

  if (compact) return <details className="manual-identity-tags manual-identity-tags--compact" aria-label="角色、作品与画师"
    open={compactOpen} onToggle={event => {if (event.target === event.currentTarget) setCompactOpen(event.currentTarget.open);}}>
    <summary className="manual-identity-heading"><strong>角色、作品与画师</strong><span>· {tagCount ? `已选 ${tagCount} 项` : "可选"}</span></summary>
    {fields}
    <div className="manual-identity-notes">
      <details className="manual-identity-help"><summary>填写说明</summary>{help}{normalizationHelp}{updateHint}</details>
      <details className="manual-identity-preview"><summary>查看 tag 预览</summary>{tagPreview}</details>
    </div>
  </details>;

  return <details className="conversation-layer manual-identity-tags">
    <summary>手动角色、作品与画师 tag（可选）</summary>
    {help}
    {fields}
    {normalizationHelp}
    {tagPreview}
    {updateHint}
  </details>;
}
