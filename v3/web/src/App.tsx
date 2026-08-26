import {useEffect, useState} from "react";
import {BrowserRouter, Navigate, Route, Routes} from "react-router-dom";
import {ApiClientError, initializeApp} from "./lib/api";
import type {BootstrapResponse} from "./lib/types";
import {AppShell} from "./components/AppShell";
import {ErrorState, LoadingState} from "./components/States";
import {TagDetailPage} from "./pages/TagDetailPage";
import {TagSearchPage} from "./pages/TagSearchPage";
import {WorkbenchPage} from "./pages/WorkbenchPage";
import {GenerationPage} from "./pages/GenerationPage";
import {GalleryPage} from "./pages/GalleryPage";

export default function App() {
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);

  useEffect(() => {
    initializeApp().then(setBootstrap).catch((caught) => setError(caught as ApiClientError));
  }, []);

  if (error) return <StartupFrame><ErrorState message={error.message} requestId={error.requestId} /></StartupFrame>;
  if (!bootstrap) return <StartupFrame><LoadingState label="正在建立本地安全会话…" /></StartupFrame>;
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell bootstrap={bootstrap} />}>
          <Route index element={<Navigate to="/workbench" replace />} />
          <Route path="workbench" element={<WorkbenchPage remoteEnabled={Boolean(bootstrap.features.remote_generation)} naturalLanguageEnabled={Boolean(bootstrap.features.natural_language_parse)} localTranslationEnabled={Boolean(bootstrap.features.local_translation)} />} />
          <Route path="tags" element={<TagSearchPage />} />
          <Route path="tags/:name" element={<TagDetailPage />} />
          <Route path="generate" element={<GenerationPage remoteEnabled={Boolean(bootstrap.features.remote_generation)} />} />
          <Route path="gallery" element={<GalleryPage enabled={Boolean(bootstrap.features.gallery)} />} />
          <Route path="*" element={<Navigate to="/workbench" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

function StartupFrame({children}: {children: React.ReactNode}) {
  return <main className="startup-frame"><div className="startup-brand"><span>A</span><strong>ANIMA Prompt Studio</strong></div>{children}</main>;
}
