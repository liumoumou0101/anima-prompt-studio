export function LoadingState({label = "正在读取本地数据…"}: {label?: string}) {
  return (
    <div className="state-panel" role="status">
      <span className="loading-orbit" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function EmptyState({title, detail}: {title: string; detail: string}) {
  return (
    <div className="state-panel state-panel--empty">
      <span className="state-glyph" aria-hidden="true">⌁</span>
      <h2>{title}</h2>
      <p>{detail}</p>
    </div>
  );
}

export function ErrorState({message, requestId, onRetry}: {message: string; requestId?: string; onRetry?: () => void}) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <span className="state-glyph" aria-hidden="true">!</span>
      <h2>这一步没有完成</h2>
      <p>{message}</p>
      {requestId && <code>Request {requestId}</code>}
      {onRetry && <button className="button button--secondary" onClick={onRetry}>重新尝试</button>}
    </div>
  );
}
