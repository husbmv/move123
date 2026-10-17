# AGENTS.md — 项目约束（AI 助手与维护者必读）

## 工作流铁律：先本地打包，测试确认后再提交

1. **任何代码改动完成后，先在本地跑测试并打包出可安装的 DMG / 安装包**，把产物路径交给维护者实测。
2. **维护者实测确认没问题之前，禁止 `git commit`、`git push`、打 tag。**
3. 发版（`git tag vX.Y.Z`）必须在本地安装包验收通过之后进行；tag 一旦推送，CI 会自动创建公开 Release。

### 本地测试 + 打包命令速查（macOS）

```bash
# 1. 后端测试
cd desktop/backend
.venv/bin/python -m pytest tests/ -q

# 2. 前端构建（产物内嵌进后端二进制）
cd ../web && npm ci && npm run build

# 3. PyInstaller 打后端侧车
cd ..
python -m PyInstaller backend.spec --noconfirm --distpath backend-dist --workpath backend-build

# 4. Electron 出包（产物在 desktop/release/）
npm ci && npm run dist:mac
```

Windows 包无法在 macOS 上交叉构建（PyInstaller 限制），由 CI 在 Windows runner 上构建。

## 版本号规则（客户端 + 油猴脚本）

每次发版版本号 +1（`1.5.0 → 1.5.1`）。末位到 10 不写成 `.10`，而是往前进一位、末位归零（`1.5.9 → 1.6.0`）；第二位到 10 再往前进一位、后面归零（`1.9.x → 2.0.0`）。只递增、不回退。

- **桌面客户端**：打开 https://github.com/weige146/123Cloud/releases 看 Latest release 的 tag（`vX.Y.Z`），据此把 `desktop/package.json` 的 `version` 写成 X.Y.Z+1。发版 = 本地打包验收通过后 push tag `vX.Y.Z`，CI 自动以 tag 作为应用版本出包并创建公开 Release（打包时 `npm version` 用 tag 覆盖本地 version）。
- **油猴脚本**：打开 https://greasyfork.org/zh-CN/scripts/592236-123-%E5%8A%A9%E6%89%8B 看页面元信息的「版本：x.y.z」（页面正文/文档里手写的版本号可能过时，不要信），据此把脚本头部 `// @version` 写成 x.y.z+1。快速核对：`curl -s https://update.greasyfork.org/scripts/592236.meta.js | grep @version`。
- **更新日志写法（`SCRIPT_CHANGELOG`，维护者 2026-10-13 定、2026-10-14 补）**：只写用户看得见的变化，**一个功能或优化一行**、小白话——单行、一眼看完（≤40 字），**有几条写几条、不凑数、不设条数下限**（2026-10-14 取消「每版至少 3 条」，机检同步放宽为 ≥1），不出现字段名/函数名/属性名（`data-c123-*`）/文件名（`*.mjs`）/代码符号这类实现细节；写「用户看到什么变了」而不是「代码怎么改的」（例：`整理后的文件名里不再出现 SDR，以前配置里的残留也会自动清掉`）。机检在 `changelog-notice.test.mjs`（≥1 条 / 单行 / 每条 >8 字且 ≤40 字 / 实现细节黑名单），历史版本条目不必回改（更新弹窗只按当前版本号取 `SCRIPT_CHANGELOG` 里对应那一版）。
- **客户端自动更新**（1.4.4 起内置，1.4.5 起 mac 闭环）：应用启动 10 秒后与每 6 小时检查 GitHub Release，发现新版后台自动下载，设置页「重启并安装」。mac 的 Release 必须同时上传 dmg 与 zip（electron-updater 的 MacUpdater 只认 zip，缺 zip 直接报错走「到发布页手动下载」分支），Windows 认 exe + latest.yml。1.4.4 及更早的已装版本提示「未包含自动更新组件/请到发布页下载」属预期——引导手动安装一次带更新组件的版本即可；mac 端 v1.4.4 的 Release 没有发 zip，同样要手动装一次 1.4.5 才闭环，之后版本互升全自动。

- 脚本文件：`123-helper/123-helper.user.js`（2026-09-21 起油猴脚本目录解散、123-helper 移至仓库根目录；原 `油猴脚本/tmdb-helper` 已删除，由 `tmdb-editor-skill/` 接替），版本号写在头部 `// @version`。

## 两端技术识别同步铁律（油猴整理识别 ↔ 桌面影库，2026-09-20 维护者定）

技术识别字段在**两端各有一套实现**，语义必须保持一致：油猴 `DEFAULT_FIXED_MAPPINGS` + `inferTechnicalFields`（含 `findAudioMapping`/标题 token 表/stemHasTagMarker/SEASON_TECHNICAL_SUFFIX_SOURCE）↔ 桌面 `movie_library.py` 的 `_TECH_RESOURCE/_TECH_DYNAMIC/_TECH_VIDEO/_TECH_AUDIO/_TECH_SOURCES/_TECH_EDITIONS`。字段集 = resourceType / mediaSource / dolbyVision / dynamicRange / videoCodec / audioCodec / frameRate / colorDepth / highQuality / originalEdition（+ videoFormat 仅油猴；colorDepth/mediaSource 自 1.3.16 起两端都有）。**任何一侧增删别名、输出名或字段，必须同步另一侧**，并跑 `123-helper/tests/technical-fields.test.mjs` 与 `desktop/backend/tests/test_movie_library.py` 的技术用例。已知的有意不对齐（不要机械照搬）：桌面影库另有粗粒度 `_RESOLUTIONS/_EDITIONS` 分层（4K/1080p/720p/SD + REMUX/BluRay/WEB-DL…，影库自有设计）；投稿链路 `submission.py`/`version_semantics.py` 是独立的命名字段表；油猴音频带声道/Atmos/JOC 后缀拼接，桌面只出编码名；桌面分面（effects/videoCodecs/audioCodecs）只暴露三行。别名带正则语义（`DD+` 的 `+`、`H.265` 的点）时，归一化/边界规则两端都要防「符号剥掉后退化遮蔽别的条目」（踩过：`DD+`→`DD` 前缀遮蔽致 DD2.0 误判 DDP）。**油猴侧默认映射表（`DEFAULT_FIXED_MAPPINGS`）的任何增删对存量用户不自动生效**——`fixedMappings` 是首装快照存进用户配置、`normalizeConfig` 每次读的是用户存储，必须同时加 schemaVersion 迁移补种（参照 `seedAvsVideoCodecMappings`/`migrateBackendAlignedFixedMappings`，当前 schemaVersion=15，补种只跑一次、用户删除/自建同名条目均尊重）并跑 `tests/fixed-mappings-seed.test.mjs`（踩过：只改默认表发布 1.3.17 首测，老配置 AVS2 照样不识别）。

## 架构备忘

- `desktop/backend/app/main.py` — FastAPI 路由层；投稿/搬运的统一分流入口是 `route_submission_text`（油猴脚本 `POST /api/submission/submit` 与后台提交共用）。
- `desktop/backend/app/transfer_service.py` — 搬运任务调度门面：入队、去重、并发、暂停窗口、115 账号池健康、直链轮换、通知钩子。
- `desktop/backend/app/transfer_pipeline.py` — 单次搬运的六阶段管线：解析 → 规划 → 秒传 → 离线 → 等待 → 收尾；`OfflineDownloadManager` 滚动提交 + 统一等待（同时在 123 排队的离线任务数上限 = 后台"并发"配置 1-5，完成一个自动补交；完成判定 = 列目录 + 大小比对；名额池自 1.4.10 起全局跨任务共享）。
- `desktop/backend/app/sha1_cloud.py` — 共享 SHA1 秒传库客户端（API 客户端 `Sha1ApiClient` 优先，数据库直连 `Sha1CloudClient` 仅兼容旧 SHA1DB_* 配置；全部网络操作尽力而为、按未命中处理，连败熔断：API 5 次/5 分钟、DB 3 次/10 分钟）。
- `desktop/backend/app/logsetup.py` — 统一日志：控制台 + 落盘轮转 + 内存环形缓冲（`GET /api/logs`）。应用日志必须是**大白话流程叙述**，第三方库一律降噪到 WARNING。
- `desktop/backend/app/telegram_session.py` — TG 用户 Session 获取：手机号 → 验证码 →（可选两步验证密码）→ StringSession，登录会话只在内存里活 10 分钟。配套接口在 main.py：`/api/submission/telegram/session/start|verify|cancel`；登录成功后 session 由后端直接写回投稿配置的 `telegramApi`，并调 `reset_telegram_client_state()` 让旧帖清理的 client 单例重建。
- 离线等待阶段**不打印心跳日志**：后台「离线轮询间隔」默认 15 秒，每轮一条「…秒后再检查」会把每个文件的成功/失败全部淹掉。现在只保留成功/失败；每 60 秒做一次静默存档，仅用于及时感知任务被删除/取消。
- Telegram 有两条通道：**投稿入口走 HTTP**（油猴脚本 `POST /api/submission/submit`，与后台共用 `route_submission_text` 分流），**最小化轮询**（`telegram_callback_polling_loop`）只处理草稿预览按钮回调和按钮触发的后续输入，不接收投稿文本；搬运任务通知、投稿预览、频道发布均为出站。
- `desktop/backend/app/movie_library_db.py` — 影库数据库层（**数据库优先架构**）：三张表 `library_sources`（来源）/ `library_works`（作品，dir 主键）/ `library_work_files`（作品内文件），都在同一个 `cloud123.db`（WAL）。导入规则：dir 已存在则跳过（保留先入库的），同名来源重新导入 = 先清该来源旧数据再插（可更新），删除来源级联删其作品与文件。搜索走 `norm_title/pinyin` 索引 + SQL 分页，分类 GROUP BY、统计 SUM，导入时就算好拼音与归一化标题。
- `desktop/backend/app/movie_library.py` — 影库解析/格式工具（移植自"123云盘影库搜索-本地版"）：只保留纯函数（`parse_library_content` 等 123FastLink / 123pan-strm / V1/V2 秒传文本 / `.123share` 解析，`{tmdb-N}` 与 `[tmdb-N]` 都认）、`aggregate_works` 按 tmdb 标记聚合（Season 并入）、`split_category`、`fmt_size`、拼音键。**已删除** `Library`/`LibraryManager`/`MovieLibraryService`/watcher：不再有"扫描指定文件夹 + mtime 热重载 + kv 索引缓存"那套，用户手动选 JSON 入库后源 JSON 删掉也能查。
- 配套 `library_transfer.py`（复用已授权 123 OpenAPI 的 `md5_reuse`+`ensure_path` 转存到云盘）。**客户端的「分享链接提取入影库」功能已移除**（`share_extractor.py` 模块与 `/api/library/share/*`、`/api/library/file-types` 路由已删，`library_share_history` 表不再建；影库只支持本地导入：浏览器上传 / 文件选择器 / 文件夹批量），油猴脚本侧的「分享链接免转存生成秒传」不受影响、保留在脚本里。
- 路由在 main.py `/api/library/*`：数据接口（search/files/export/categories/transfer）在配置了 `movieLibrary.token` 后必须带令牌（query `token=` 或 Bearer，恒时比较）；`GET /api/library/config` 的明文令牌只回给 127.0.0.1 来源。导入入口三个：`POST /api/library/import`（浏览器上传原始内容）、`POST /api/library/import/paths`（桌面端文件选择器多选，后端按路径读）、`POST /api/library/import/dir`（文件夹一次性批量导入，递归子目录、跳过 `_checkpoints`/隐藏目录、深度 ≤3，不驻留监控）；来源管理 `GET /api/library/sources` + `POST /api/library/sources/delete`（也支持 DELETE 方法）。`POST /api/library/scan` 与配置里的 `folder`/`autoScan`/`intervalSec` 已移除（导出目录 `exportDir` 保留，留空则落到 `DATA_DIR/秒传文件导出`）。影库接口面向油猴脚本"随时随地搜索转存"，与投稿接口同源同端口（`设置 → 服务端口`），客户端保持默认 127.0.0.1 监听。海报与 TMDB 详情走后端代理（`/api/library/poster|tmdb/{id}`，客户端投稿配置的 TMDB TOKEN，sqlite kv 缓存）。
- 油猴脚本（`123-helper/123-helper.user.js`）不改动：它对 `/api/submission/submit` 的响应有硬校验（`ok===true` 且 `draftCount`、`sentCount` 必须等于批次条数），后端必须保持这个响应契约。
