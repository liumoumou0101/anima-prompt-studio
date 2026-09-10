import {useEffect, useState} from "react";
import {apiRequest} from "../lib/api";

type LlmService = {
  id: string; name: string; type: string; base_url: string;
  api_key_masked: string; api_key_exists: boolean;
  supports_vision?: boolean; ingest_enable_thinking?: boolean;
  llm_models: {name: string; display_name: string; is_default: boolean}[];
};
type LlmSettingsResponse = {services: LlmService[]; current: {service: string; model: string}};

export function LlmSettingsPanel() {
  const [settings, setSettings] = useState<LlmSettingsResponse | null>(null);
  const [error, setError] = useState("");
  const [serviceId, setServiceId] = useState("");
  const [serviceType, setServiceType] = useState("openai_compatible");
  const [modelName, setModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [supportsVision, setSupportsVision] = useState(false);
  const [ingestThinking, setIngestThinking] = useState(false);

  useEffect(() => {
    apiRequest<LlmSettingsResponse>("/api/v3/llm/settings").then((payload) => {
      setSettings(payload);
      setServiceId(payload.current.service || "custom");
      setModelName(payload.current.model);
      const service = payload.services.find((s) => s.id === payload.current.service);
      setBaseUrl(service?.base_url || "");
      setServiceType(service?.type || "openai_compatible");
      setSupportsVision(Boolean(service?.supports_vision));
      setIngestThinking(Boolean(service?.ingest_enable_thinking));
    }).catch((caught: Error) => setError(caught.message));
  }, []);

  const selectedService = settings?.services.find((s) => s.id === serviceId);
  function selectService(id: string) {
    const service = settings?.services.find((s) => s.id === id);
    setServiceId(id);
    setModelName(service?.llm_models.find((m) => m.is_default)?.name || service?.llm_models[0]?.name || "");
    setBaseUrl(service?.base_url || "");
    setServiceType(service?.type || "openai_compatible");
    setSupportsVision(Boolean(service?.supports_vision));
    setIngestThinking(Boolean(service?.ingest_enable_thinking));
    setApiKey("");
    setClearKey(false);
    setNotice("");
    setError("");
  }

  async function save(test: boolean) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiRequest("/api/v3/llm/settings", {method: "PUT", body: JSON.stringify({
        service_id: serviceId, service_type: serviceType, model_name: modelName.trim(),
        base_url: baseUrl.trim(), api_key: apiKey || null, clear_api_key: clearKey,
        supports_vision: supportsVision, ingest_enable_thinking: ingestThinking,
      })});
      setApiKey("");
      setClearKey(false);
      setSettings(await apiRequest<LlmSettingsResponse>("/api/v3/llm/settings"));
      setNotice("配置已保存。尚未测试连接。");
      if (test) {
        const result = await apiRequest<{message: string}>("/api/v3/llm/test", {method: "POST", body: "{}"});
        setNotice(result.message);
      }
    } catch (caught) { setError((caught as Error).message); }
    finally { setBusy(false); }
  }

  return <details className="llm-settings" open>
    <summary>LLM 服务配置（API Key / 模型）</summary>
    {!settings ? <p>{error || "正在读取 LLM 配置…"}</p> : <>
      <fieldset disabled={busy} className="llm-settings-grid">
        <label>服务商<select value={serviceId} onChange={(e) => selectService(e.target.value)}>
          {settings.services.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          {!settings.services.some((s) => s.id === "custom") && <option value="custom">自定义 API</option>}
        </select></label>
        {serviceId === "custom" && !selectedService && <label>协议<select value={serviceType} onChange={(e) => setServiceType(e.target.value)}>
          <option value="openai_compatible">OpenAI 兼容</option><option value="ollama">Ollama</option>
        </select></label>}
        <label>API 地址（Base URL）<input type="url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="https://你的服务地址/v1" /></label>
        <label>模型名称<input list="llm-model-options" value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="填写服务商实际支持的模型 ID" />
          <datalist id="llm-model-options">{selectedService?.llm_models.map((m) => <option key={m.name} value={m.name}>{m.display_name}</option>)}</datalist>
        </label>
        <label>API Key<input type="password" disabled={clearKey} value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={selectedService?.api_key_exists ? "已保存（留空不修改）" : "粘贴 API Key；本地服务可留空"} autoComplete="new-password" /></label>
        <label className="llm-key-clear"><input type="checkbox" checked={clearKey} onChange={(e) => {setClearKey(e.target.checked); setApiKey("");}} />清除已保存的 Key</label>
        <div className="llm-settings-actions">
          <label><input type="checkbox" checked={supportsVision} onChange={e => setSupportsVision(e.target.checked)} />当前模型支持图像理解</label>
          <label><input type="checkbox" checked={ingestThinking} onChange={e => setIngestThinking(e.target.checked)} />分析参考图时启用思考（可能更慢）</label>
          <button className="button" type="button" disabled={!baseUrl.trim() || !modelName.trim()} onClick={() => void save(false)}>保存配置</button>
          <button className="button button--primary" type="button" disabled={!baseUrl.trim() || !modelName.trim()} onClick={() => void save(true)}>{busy ? "正在处理…" : "保存并测试连接"}</button>
        </div>
      </fieldset>
      <p className="llm-settings-note">连接测试会向所填服务发送一次短文本，可能产生少量费用。模型列表仅供参考，以服务商实际权限为准。Key 明文保存在本机，请勿分享配置文件。更换地址需重新输入或清除 Key。</p>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </>}
  </details>;
}
