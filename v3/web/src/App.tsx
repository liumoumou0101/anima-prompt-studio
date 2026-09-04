import {useEffect, useState} from "react";
import {BrowserRouter, Navigate, Route, Routes} from "react-router-dom";
import {apiRequest, ApiClientError, initializeApp} from "./lib/api";
import {loadGallery, primeGallery} from "./lib/galleryStore";
import type {BootstrapResponse, GalleryProcessJob, GenerationRunListResponse} from "./lib/types";
import {AppShell} from "./components/AppShell";
import {ErrorState, LoadingState} from "./components/States";
import {TagDetailPage} from "./pages/TagDetailPage";
import {TagSearchPage} from "./pages/TagSearchPage";
import {TagGroupPage} from "./pages/TagGroupPage";
import {TagUngroupedPage} from "./pages/TagUngroupedPage";
import {WorkbenchPage} from "./pages/WorkbenchPage";
import {DirectPromptPage} from "./pages/DirectPromptPage";
import {GenerationPage} from "./pages/GenerationPage";
import {GalleryPage} from "./pages/GalleryPage";
import {SettingsPage} from "./pages/SettingsPage";
import {ArtistSearchPage} from "./pages/ArtistSearchPage";
import {ArtistDetailPage} from "./pages/ArtistDetailPage";

export default function App() {
  const [bootstrap, setBootstrap] = useState<BootstrapResponse | null>(null);
  const [error, setError] = useState<ApiClientError | null>(null);

  useEffect(() => {
    initializeApp().then(setBootstrap).catch((caught) => setError(caught as ApiClientError));
  }, []);

  useEffect(() => {
    if (!bootstrap?.features.gallery) return;
    let canceled = false;
    const timer = window.setTimeout(() => {
      if (!canceled) void primeGallery().catch(() => undefined);
    }, 250);
    return () => { canceled = true; window.clearTimeout(timer); };
  }, [bootstrap]);

  useEffect(() => {
    if (!bootstrap?.features.gallery || !bootstrap.features.remote_generation) return;
    let canceled = false;
    let timer = 0;
    let initialized = false;
    const completedRuns = new Set<string>();
    const completedJobs = new Set<string>();
    const activeStates = new Set(["draft", "connecting", "preparing", "queued", "starting", "running", "downloading"]);

    const poll = async () => {
      const [runsResult, jobsResult] = await Promise.allSettled([
        apiRequest<GenerationRunListResponse>("/api/v3/generation-runs?limit=20"),
        apiRequest<{jobs: GalleryProcessJob[]}>("/api/v3/gallery/process"),
      ]);
      if (canceled) return;

      const runs = runsResult.status === "fulfilled" ? runsResult.value.items : [];
      const jobs = jobsResult.status === "fulfilled" ? jobsResult.value.jobs : [];
      const finishedRuns = runs.filter((run) => run.state === "completed" && run.artifact_count > 0);
      const finishedJobs = jobs.filter((job) => job.state === "completed" && Boolean(job.resultPath));
      const hasNewOutput = initialized && (
        finishedRuns.some((run) => !completedRuns.has(run.id))
        || finishedJobs.some((job) => !completedJobs.has(job.id))
      );
      finishedRuns.forEach((run) => completedRuns.add(run.id));
      finishedJobs.forEach((job) => completedJobs.add(job.id));
      initialized = true;

      if (hasNewOutput) await loadGallery({refresh: true, reason: "generation"}).catch(() => undefined);
      if (canceled) return;
      const active = runs.some((run) => activeStates.has(run.state)) || jobs.some((job) => activeStates.has(job.state));
      timer = window.setTimeout(() => void poll(), active ? 2500 : 10000);
    };

    timer = window.setTimeout(() => void poll(), 1200);
    return () => { canceled = true; window.clearTimeout(timer); };
  }, [bootstrap]);

  if (error) return <StartupFrame><ErrorState message={error.message} requestId={error.requestId} /></StartupFrame>;
  if (!bootstrap) return <StartupFrame><LoadingState label="正在建立本地安全会话…" /></StartupFrame>;
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell bootstrap={bootstrap} />}>
          <Route index element={<Navigate to="/workbench" replace />} />
          <Route path="workbench" element={<WorkbenchPage modelProfiles={bootstrap.model_profile_options} remoteEnabled={Boolean(bootstrap.features.remote_generation)} naturalLanguageEnabled={Boolean(bootstrap.features.local_translation)} localTranslationEnabled={Boolean(bootstrap.features.local_translation)} />} />
          <Route path="direct" element={<DirectPromptPage modelProfiles={bootstrap.model_profile_options} remoteEnabled={Boolean(bootstrap.features.remote_generation)} />} />
          <Route path="tags" element={<TagSearchPage />} />
          <Route path="tags/groups/:groupName" element={<TagGroupPage />} />
          <Route path="tags/ungrouped" element={<TagUngroupedPage />} />
          <Route path="tags/:name" element={<TagDetailPage />} />
          <Route path="artists" element={<ArtistSearchPage />} />
          <Route path="artists/:name" element={<ArtistDetailPage />} />
          <Route path="generate" element={<GenerationPage remoteEnabled={Boolean(bootstrap.features.remote_generation)} />} />
          <Route path="gallery" element={<GalleryPage enabled={Boolean(bootstrap.features.gallery)} />} />
          <Route path="settings" element={<SettingsPage remoteEnabled={Boolean(bootstrap.features.remote_generation)} />} />
          <Route path="*" element={<Navigate to="/workbench" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

function StartupFrame({children}: {children: React.ReactNode}) {
  return <main className="startup-frame"><div className="startup-brand"><span>A</span><strong>ANIMA Prompt Studio</strong></div>{children}</main>;
}
