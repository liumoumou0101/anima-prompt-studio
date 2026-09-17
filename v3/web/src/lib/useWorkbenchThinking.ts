import {useCallback, useEffect, useRef, useState} from "react";
import {apiRequest} from "./api";

export type LlmSettingsResponse = {
  services: {
    id: string; name: string; type: string; base_url: string;
    api_key_masked: string; api_key_exists: boolean;
    supports_vision?: boolean; ingest_enable_thinking?: boolean; workbench_enable_thinking?: boolean;
    llm_models: {name: string; display_name: string; is_default: boolean}[];
  }[];
  current: {
    service: string; model: string; workbench_enable_thinking?: boolean;
    thinking?: {mode: "switchable" | "required" | "unverified"; message: string};
  };
};

export function useWorkbenchThinking() {
  const [current, setCurrent] = useState<LlmSettingsResponse["current"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(false);
  const epoch = useRef(0);
  const saveLock = useRef(false);

  const refresh = useCallback(async (saveWarning = "") => {
    const requestEpoch = ++epoch.current;
    setLoading(true); setError("");
    try {
      const payload = await apiRequest<LlmSettingsResponse>("/api/v3/llm/settings");
      if (!payload.current || typeof payload.current.service !== "string" || typeof payload.current.model !== "string") {
        throw new Error("LLM 配置格式有误，请重新读取。");
      }
      if (mounted.current && requestEpoch === epoch.current) {
        setCurrent(payload.current);
        setError(saveWarning ? `${saveWarning}已重新读取当前配置，请以当前显示为准。` : "");
      }
    } catch (caught) {
      if (mounted.current && requestEpoch === epoch.current) {
        setCurrent(null); setError(`${saveWarning}无法读取深度思考状态：${(caught as Error).message}`);
      }
    } finally {if (mounted.current && requestEpoch === epoch.current) setLoading(false);}
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {mounted.current = false; epoch.current += 1;};
  }, [refresh]);

  async function toggle() {
    if (!current || loading || saveLock.current) return;
    saveLock.current = true;
    setSaving(true); setError("");
    try {
      await apiRequest("/api/v3/llm/settings", {method: "PUT", body: JSON.stringify({
        service_id: current.service, model_name: current.model,
        workbench_enable_thinking: !current.workbench_enable_thinking,
      })});
      if (mounted.current) await refresh();
    } catch (caught) {
      if (mounted.current) await refresh(`深度思考设置保存结果未确认：${(caught as Error).message}。`);
    } finally {
      saveLock.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  const enabled = Boolean(current?.workbench_enable_thinking);
  const mode = current?.thinking?.mode || "unverified";
  const unavailableReason = loading ? "正在读取深度思考状态…" : !current ? "深度思考状态未读取，请重新读取配置。"
    : saving ? "正在保存深度思考设置…" : mode === "required" && !enabled ? "该模型必须思考，请开启深度思考或更换模型。" : "";
  const message = current?.thinking?.message || "此模型的思考开关尚未验证，服务商可能忽略设置。";
  return {current, enabled, mode, message, loading, saving, error, unavailableReason, refresh, toggle};
}
