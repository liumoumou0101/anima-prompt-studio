# V3 Web

React/Vite/TypeScript 产品层。浏览器只调用统一的 `/api/v3`，不直接读取 SQLite、Parquet 或 V2 LocalStorage。

```powershell
npm install
npm run dev
npm run typecheck
npm run test
npm run build
```

开发服务器通过 `V3_API_TARGET` 把 `/api` 与 `/health` 代理到本地 V3 API。正式构建产物由同一个 loopback API 服务，避免 CORS 和多后端边界。

生产模式从 `v3/` 启动：

```powershell
anima-v3-api `
  --reference-db .local\packs\anima-v3-dso-0636f762-r1\reference.db `
  --frontend-dist web\dist
```

打开命令输出的 `bootstrap_url`。前端仅把 session token 放在当前标签页的 `sessionStorage`，一次性 bootstrap token 会在交换后从地址栏移除。
