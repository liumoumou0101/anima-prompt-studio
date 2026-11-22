# 画师串库与样品实施计划

用户已授权实施聊天中讨论的方案；主要使用 Anima，其他模型必须明确标注，每串尽量至少一张真实样品。沿用 single-workbench 隔离工作区，保留已完成改造和用户改动。

## 本次范围

1. 独立画师串记录复用 personal-tags.db，原始正负向文本逐字保存，模型/语法/来源/收藏/备注；真实样品独立保存，完整生成上下文可查看。修改提示词或模型后旧样品标明旧版，未有当前样品的条目标为待补样品。
2. 画师页面增加单个画师/画师串入口，搜索、模型筛选、收藏、新建编辑、上传样品、JSON 备份导入导出。已有参考图库提供经过人工核对的五组 Anima 候选，收藏时复制图片与元数据；无网络抓取、无付费生成。
3. 工作台正向提示词附近增加紧凑的画师串选择器，展示缩略图、模型、样品状态。一次只管理一组，切换替换原管理片段；对手动修改的片段解除管理，避免误删正文。每次调用/移除进入现有多步撤销和持久历史。AI 改写保留活动串字面文本。
4. 后端冻结画师串快照在 requirements.layers.style.artist_preset；历史与生成来源自然携带。旧合同无串时兼容，新增只读控制字段不能由模型覆盖。

## 共享合同

ArtistPresetWrite: name, positive, negative, model_family(anima/sdxl/novelai/other/unknown), model_label, syntax(comfy/novelai/plain/unknown), source_url, source_author, notes, favorite。字符串默认空，model_family/syntax 默认 unknown，favorite 默认 false。positive/negative 不 trim、不重排，至少一个非空。

ArtistPreset = Write + id, revision, content_hash, created_at, updated_at, samples[], ready。Sample = id, content_hash, image_url, width, height, model_label, source_url, caption, full_positive, full_negative, parameters(object), source_kind(upload/reference), source_id, created_at。ready 表示当前 content_hash 有样品，绝不表示本机效果验证。

API /api/v3/artist-presets: GET -> {items}; POST Write -> record; PUT /{id} Write+expected_revision -> record; DELETE /{id}?expected_revision ->204; POST /{id}/samples multipart file + metadata JSON(expected_revision, caption, model_label, source_url, full_positive, full_negative, parameters) ->record; DELETE /{id}/samples/{sample_id}?expected_revision ->record; GET /{id}/samples/{sample_id}/content ->image. GET /suggestions ->{items:[{reference_id,name,positive,model_label,source_url,thumbnail_url,notes}]}; POST /from-reference {reference_id} ->record (idempotent for curated candidate).

Export GET /export -> versioned JSON with embedded sample bytes; import POST /import-preview {document} -> {items,duplicates,warnings,token}; POST /import {document,token} -> {items,skipped}. Bounded JSON/body/image validation; never accept arbitrary local filesystem paths or fetch arbitrary URLs. API create registration owned by root.

Frozen snapshot: id, revision, name, positive, negative, model_family, model_label, syntax, source_url, content_hash. No image blobs in requirements. UI-managed ranges belong in LocalConversation.artistPresetPlacement (optional); snapshot stays frozen. A manual edit intersecting the range detaches the entire active preset but keeps text, with a notice. Appending/replacing preserve literal raw text and unrelated prompt regions. Reconcile AI return only by unique exact block match, ambiguity detaches UI management safely.

## 分工与验证

- Storage/API agent: store/media/export-import/reference candidates + focused API/store tests. Does not edit app.py.
- Prompt agent: Pydantic frozen snapshot, deterministic AI preservation, TS snapshot type and pure application/range mapping functions + tests. Does not edit workbench page.
- Library UI agent: artistPreset API client, library page/style/tests; no App.tsx or existing ArtistSearchPage changes.
- Root: workbench picker, route/nav registration, integration, review, responsive visual verification and final baseline-safe original-project sync.

Run focused regressions then full backend/frontend suite and build with bundled Node 24.19.0. Verify 2560×1440 plus scaled/narrow viewport. Sync only changed feature files if original content still matches captured baseline; back up originals first. New reference-derived presets add only after backup, never overwrite user records. Record samples as source-declared original-prompt examples with missing seed/workflow explicitly unknown.
