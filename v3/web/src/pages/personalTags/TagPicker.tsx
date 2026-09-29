import {Check, Plus} from "@phosphor-icons/react";
import type {CompositionItem, TagRecord} from "../../lib/personalTags";

export function TagPicker({items, selected, onAdd, onEdit}: {items: TagRecord[]; selected: CompositionItem[]; onAdd: (tag: TagRecord, side: "positive" | "negative") => void; onEdit: (tag: TagRecord) => void}) {
  return <div className="personal-tags-cards">{items.map(tag => {
    const chosen = selected.some(item => item.source_tag_id === tag.id && item.polarity === "positive");
    return <article className={`personal-tags-card${chosen ? " is-selected" : ""}`} key={tag.id}>
      <div><strong>{tag.display_name}</strong>{tag.kind === "fragment" && <small className="personal-tags-kind">片段</small>}</div>
      <p>{tag.content}</p>
      <div className="personal-tags-card-actions">
        <button type="button" aria-label={`加入正向 ${tag.display_name}`} aria-pressed={chosen} onClick={() => onAdd(tag, "positive")}>{chosen ? <Check /> : <Plus />}<span>正向</span></button>
        <button type="button" aria-label={`加入负向 ${tag.display_name}`} aria-pressed={selected.some(item => item.source_tag_id === tag.id && item.polarity === "negative")} onClick={() => onAdd(tag, "negative")}>负向</button>
        <button type="button" aria-label={`编辑 ${tag.display_name}`} onClick={() => onEdit(tag)}>详情</button>
      </div>
    </article>;
  })}</div>;
}
