import {useEffect, useRef, useState} from "react";
import {CaretDown, CaretRight, Folder} from "@phosphor-icons/react";
import type {CategoryRecord} from "../../lib/personalTags";

export function CategoryTree({categories, selected, onSelect}: {categories: CategoryRecord[]; selected: string | null; onSelect: (id: string | null) => void}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(categories.filter(item => item.parent_id === null).map(item => item.id)));
  const knownRoots = useRef(new Set<string>());
  useEffect(() => {const fresh = categories.filter(item => item.parent_id === null && !knownRoots.current.has(item.id)).map(item => item.id); if (fresh.length) {fresh.forEach(id => knownRoots.current.add(id)); setExpanded(previous => new Set([...previous, ...fresh]));}}, [categories]);
  const children = (parent: string | null) => categories.filter(item => item.parent_id === parent).sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const branch = (parent: string | null, depth = 0): React.ReactNode => children(parent).map(item => {
    const hasChildren = children(item.id).length > 0;
    const isExpanded = expanded.has(item.id);
    return <li key={item.id}>
      <div className={`personal-tags-category-row${selected === item.id ? " is-selected" : ""}`} style={{paddingInlineStart: `${depth * 14 + 4}px`}}>
        {hasChildren ? <button type="button" aria-label={`${isExpanded ? "收起" : "展开"}分类 ${item.name}`} aria-expanded={isExpanded} onClick={() => setExpanded(previous => {const next = new Set(previous); if (next.has(item.id)) next.delete(item.id); else next.add(item.id); return next;})}>{isExpanded ? <CaretDown /> : <CaretRight />}</button> : <span className="personal-tags-tree-spacer" />}
        <button type="button" aria-label={`选择分类 ${item.name}`} aria-current={selected === item.id ? "true" : undefined} onClick={() => onSelect(item.id)}><Folder aria-hidden="true" />{item.name}</button>
      </div>
      {hasChildren && isExpanded && <ul>{branch(item.id, depth + 1)}</ul>}
    </li>;
  });
  return <nav aria-label="个人标签分类"><button type="button" className={selected === null ? "is-selected" : ""} onClick={() => onSelect(null)}>全部分类</button><ul>{branch(null)}</ul></nav>;
}
