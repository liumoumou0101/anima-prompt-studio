import {useCallback, useEffect, useRef, useState} from "react";
import {personalTagsApi, type CategoryRecord, type TagRecord} from "../../lib/personalTags";

const PAGE_SIZE = 40;

export function usePersonalCatalog() {
  const [q, setQ] = useState("");
  const [categoryId, setCategoryId] = useState<string | null>(null);
  const [includeDescendants, setIncludeDescendants] = useState(true);
  const [trash, setTrash] = useState(false);
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<TagRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [categories, setCategories] = useState<CategoryRecord[]>([]);
  const [trashCategories, setTrashCategories] = useState<CategoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [version, setVersion] = useState(0);
  const sequence = useRef(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {setPage(0);}, [q, categoryId, includeDescendants, trash]);
  useEffect(() => {
    const current = ++sequence.current;
    setLoading(true);
    Promise.all([
      personalTagsApi.listTags({q, category_id: categoryId, include_descendants: includeDescendants, trash, offset: page * PAGE_SIZE, limit: PAGE_SIZE}),
      personalTagsApi.listCategories(false), personalTagsApi.listCategories(true),
    ]).then(([result, active, deleted]) => {
      if (current !== sequence.current) return;
      setItems(result.items); setTotal(result.total); setCategories(active); setTrashCategories(deleted); setError(null);
    }).catch(cause => {if (current === sequence.current) setError(cause instanceof Error ? cause : new Error(String(cause)));})
      .finally(() => {if (current === sequence.current) setLoading(false);});
    return () => {sequence.current++;};
  }, [q, categoryId, includeDescendants, trash, page, version]);
  return {q, setQ, categoryId, setCategoryId, includeDescendants, setIncludeDescendants, trash, setTrash,
    page, setPage, items, total, categories, trashCategories, loading, error, refresh, pageSize: PAGE_SIZE};
}
