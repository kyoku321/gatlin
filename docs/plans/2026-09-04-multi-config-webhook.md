# 多 Config 多 Webhook 设计：每套 config 的内容自动发往各自的 Teams Webhook

日期：2026-09-04
状态：待评审（先计划，未动代码）

## 背景 / 现状

当前架构：

- 单一 `data/config.json`（`-c/--config` 可覆盖路径）。`teams.webhook_url_env` 命名一个环境变量
  （默认 `HORIZON_TEAMS_WEBHOOK_URL`），URL 本体在 `.env` / K8s Secret 中，config 里不存密钥。
- 流水线 `horizon --date $D` 只负责抓取 → AI 分析 → 写
  `data/summaries/horizon-$D-<lang>.md`（每个 `ai.languages` 一份），**不发 Teams 卡片**。
- Teams 卡片由 shell 驱动（`helm_chart/templates/cronjob.yaml`）：
  1. `uv run horizon --json data/summaries/horizon-$D-ja.md` → `data/teams/horizon-$D-ja.json`
  2. `uv run horizon --trigger data/teams/horizon-$D-ja.json --webhook-env HORIZON_TEAMS_WEBHOOK_URL_JA`
- 即「内容 → webhook」映射硬编码在 cronjob 的 shell 命令里（ja → `_JA`）。
  想加第二套内容（不同 sources/digest/languages）推到另一个群，只能复制整个 data 目录 + 改脚本。

目标：

> 自由设定多套 config.json：config A 的内容 → webhook A；config B 的内容 → webhook B。
> 一次定时任务跑完全部，路由关系由配置声明，不再硬编码在脚本里。

## 关键决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| 多 config 存放 | `data/configs/<name>.json` 目录 + 命名约定；保留 `data/config.json` 为默认（向后兼容） | 现有 `StorageManager(data_dir, config_path)` 已支持任意路径，增量最小；`<name>`（文件名去后缀）成为 config 身份，用于日志、目录隔离、卡片链接 |
| 选择 / 批量 | CLI 新增 `-n/--config-name <name>` 与 `--all`（可选 `--configs a,b` 子集） | `-c` 仍支持显式路径，三者优先级：`-c` > `-n` > 默认 `config.json`；`--all` 在 CLI 层顺序执行（共享 AI 配额、避免并发打爆 API），单 config 失败不中断其他，最后汇总，任一失败 exit 1 |
| Teams 推送时机 | **流水线内自动推送**：`teams.enabled: true` 时，每写完一个语言的 summary 就 build + POST 卡片 | 「config A → webhook A」才成立：一次 `horizon -n a`（或 `--all`）= 内容 + 推送，cronjob 从三步缩成一步。`--json`/`--trigger` 保留（手工回填/调试/测试） |
| webhook URL 来源 | 沿用现有机制：每个 config 的 `teams.webhook_url_env` 指向各自环境变量（约定 `HORIZON_TEAMS_WEBHOOK_URL_<NAME>`），URL 不进 config | 现有机制零改动；`.env.example` / helm Secret 各加一行 |
| 汇总/卡片文件冲突 | 每个 named config 用子目录：`data/summaries/<name>/horizon-$D-<lang>.md`、`data/teams/<name>/...json`；**默认 config（无 name）保持平铺不变** | 平铺名会在多 config 同语言时互相覆盖；子目录方案 viewer 改动最小（nginx 加一条两段路径规则 + app.js 正则加可选前缀）；`<name>` 严格校验 `^[A-Za-z0-9][A-Za-z0-9._-]*$` 防路径穿越（`safe_output_path` 同步放宽一级） |
| 卡片内报告链接 | `build_card(..., path_prefix="")` 新参数；named config 传 `name/`，按钮 URL = `{viewer_base}/#{name}/horizon-$D-$lang.md` | viewer 的 hash 路由按文件名解析，前缀方案不需要 viewer 路由逻辑重写 |
| 推送失败语义 | 与 `WebhookNotifier` 一致：打印/记录错误、**不 raise**、不影响该 config 其余语言，也不使整个 `--all` 失败（除非流水线本身失败）；汇总行提示「N 个 webhook 推送失败」 | webhook 抖动不应毁掉一次昂贵的 AI 运行 |
| 回填模式 | `--all --date $D` 时 Teams 推送跟随现有 `notify` 语义：backfill 默认不推，需加 `--notify` | 与流水线 webhook 行为一致；**helm cronjob 必须同步加 `--notify`**（当前 shell 是显式 `--trigger` 推的，迁入流水线后要补这个 flag） |
| 部署（helm） | Secret 增加 `configs/<name>.json` 条目挂载到 `/app/data/configs/`；cronjob 命令改为 `uv run horizon --all --date $D --notify` | values 里 `configs: {a: {...}, b: {...}}` 渲染多 secret key，沿用现有 `required`/`fromJson` 防呆 |

### 备选方案（已否决，留档）

- **B. 纯 shell 循环**（`multi-run.sh` 遍历 `data/configs/*.json`，逐个 `horizon -c ... --json --trigger`）：
  不改流水线，但 `--webhook-env` 需要 shell 从 config 里读出 env 名（jq/python 二次解析），
  且文件冲突问题（同名同语言覆盖）依然要解决，收益不如流水线内推送。
- **C. 每 config 独立 data 目录**（`-d data-a`）：隔离最彻底，但 PVC 布局、viewer base、
  profiles 目录、脚本全部翻倍，运维成本高；当前需求不需要。
- **D. 平铺文件名加前缀**（`horizon-<name>-DATE-lang.md`）：viewer 免改，
  但破坏 `--json` 的语言推断正则和全部既有命名约定，侵入性更大。

## 实施步骤

### Phase 1：流水线内 Teams 自动推送（单 config 先跑通 A→A）

1. `src/models.py`
   - `TeamsConfig` 增加：
     - `enabled: bool = False`
     - `top: int = 0`（`ge=0`，0=全部；对应 `--json --top`）
     - `languages: Optional[List[str]] = None`（复用 `_normalize_language_tag` 校验器；None=全部 `ai.languages`）
2. `src/teams/card.py`
   - `build_card(parsed, viewer_base, lang, top=0, path_prefix="")`：
     报告按钮 URL 改为 `f"{viewer_base.rstrip('/')}/#{path_prefix}horizon-{date}-{lang}.md"`
     （`path_prefix` 为 `""` 或 `"name/"`，兼容现有调用）。
   - 新增 `src/teams/delivery.py`（或 card.py 内）`send_teams_card(teams_cfg, config_name, summary_md, lang, top) -> 结果对象`：
     - 解析 env：`os.environ.get(teams_cfg.webhook_url_env or DEFAULT_WEBHOOK_ENV)`；
       未设置 → warning + SKIPPED（与 WebhookNotifier 同款文案风格）
     - URL 校验复用 `validate_http_url`（`src/url_security.py`）
     - `build_card_from_markdown(...)` → `post_card(card, url)` → `is_success`（200/202）
     - 返回 `(status, status_code, detail)`，不 raise（网络/HTTP 错误都归入结果）
3. `src/orchestrator.py`
   - `__init__`：记录 `config_name`（新增构造参数，默认 `None`=默认 config）。
   - `run()` 每语言循环内、`save_daily_summary` 之后：
     若 `config.teams and config.teams.enabled and (teams.languages is None or lang in teams.languages)`
     且 `notify` 为真 → 调 `send_teams_card(...)`，按结果打印
     success/skipped/failure；统计失败数，run 结束时汇总提示。
   - 注意：`viewer_base_url` 未配置时跳过并 warning（卡片按钮无链接，属配置错误）。

**验收**：`data/config.json` 加 `teams.enabled=true` + `webhook_url_env=HORIZON_TEAMS_WEBHOOK_URL_ZH`，
`uv run horizon --hours 24` 后 zh 卡片自动进 A 群；env 未设时 warning 跳过、不影响运行。

### Phase 2：多 config 发现 + 批量运行 + 文件隔离

4. `src/storage/manager.py`
   - `save_daily_summary(date, markdown, language, subdir=None)`：
     `subdir` 非空时写 `summaries/<subdir>/...`，并校验 subdir 匹配
     `^[A-Za-z0-9][A-Za-z0-9._-]*$`（复用/扩展 `safe_output_path` 允许一级子目录）。
5. 新增 `src/configs.py`（或放 `_cli.py` 旁的小工具）
   - `resolve_config_path(data_dir, name=None, explicit=None) -> tuple[Path, str|None]`：
     返回 (config 路径, config_name)；`explicit` 优先；`name` → `data_dir/configs/<name>.json`；
     否则 `data_dir/config.json`（name=None）
   - `list_config_names(data_dir) -> list[str]`：`configs/` 下 `*.json` 的 stem，排序（排序=稳定顺序）
   - 文件不存在/JSON 非法：`--all` 时该 config 记 FAIL 并继续，不中断整批
6. `src/main.py`
   - 新参数：`-n/--config-name`、`--all`、`--configs`（逗号分隔，与 `--all` 互斥）
   - `--all`/`--configs`：
     - 对每个 name 依次：`StorageManager(data_dir, config_path)` → `load_config()` →
       `HorizonOrchestrator(config, storage, config_name=name)` → `asyncio.run(orchestrator.run(...))`
       （每个 config 独立 `asyncio.run`，隔离事件循环状态）
     - 每个 config 前后打印分隔标题 `[config <name>]`
     - 收集状态表（OK / FAIL+原因），最终打印汇总；任一失败 `exit 1`
     - 与 `--date`/`--hours`/`--notify` 组合合法；与 `--json`/`--trigger` 互斥
   - `--json`：
     - 输出路径改为镜像输入子目录：输入 `data/summaries/<name>/horizon-...md`
       → 输出 `data/teams/<name>/horizon-....json`（平铺输入保持 `data/teams/` 不变）
     - 语言推断正则扩展：`(?:^|/)(horizon-\d{4}-\d{2}-\d{2})-([a-z]{2,3})\.md$`
     - 有子目录时把 `name/` 作为 `path_prefix` 传给 `build_card`
   - `--trigger`：卡片 JSON 路径同样允许子目录；逻辑不变
   - `--all --json ...` 的组合语义：对每个 config 各自的当日 summary 逐个转换+触发
     （可选增强，若实现复杂则 Phase 2 先不支持 `--all --json/--trigger`，仅支持流水线模式，文档说明）
7. `.gitignore`：`data/configs/`（与 `data/config.json` 同级处理）

**验收**：
`data/configs/a.json`（`teams.webhook_url_env=HORIZON_TEAMS_WEBHOOK_URL_A`，zh）+
`data/configs/b.json`（`..._B`，ja）；`uv run horizon --all --hours 24` 后：
- A 群收到 a 的内容（zh 卡片，按钮指向 `/#/a/horizon-...md`）
- B 群收到 b 的内容
- `data/summaries/a/`、`data/summaries/b/` 各自独立，无覆盖
- 默认 `config.json` 行为与改动前完全一致

### Phase 3：Viewer + Helm 多 config 支持

8. `viewer/app.js`
   - `FILE_RE` 扩展为可选目录前缀：`/^([A-Za-z0-9._-]+\/)?horizon-(\d{4}-\d{2}-\d{2})-([a-z]{2,3})\.md$/`
   - `fetchList`：顶层 listing 中 `is_dir` 条目再 fetch `/summaries/<dir>/`，合并成带前缀的完整列表
   - 日期分组 chips：同日期不同 config/语言都列 chip（label：语言；同语言多 config 时显示 `<name>` 区分）
   - 语言切换条（sibling 逻辑）按「同日期 + 不同 name/lang」扩展
9. `helm_chart/templates/viewer-nginx-config.yaml`
   - 新增两条 location（保持最小放行面）：
     - `location = /summaries/<单段目录名>/` 不允许泛匹配；用正则
       `~* ^/summaries/([A-Za-z0-9][A-Za-z0-9._-]*)/$` → `autoindex_format json` + alias
     - `~* ^/summaries/[A-Za-z0-9][A-Za-z0-9._-]*/([A-Za-z0-9._-]+\.md)$` → alias 文件
   - 其余 `/summaries/*` 仍 404（config.json 等不可达原则不变）
10. `helm_chart/`
    - `values.yaml`：`cron.configs: []`（每项 `{name, config: {...}}`）
    - Secret 模板：`configs: <name>: <json>` 渲染为 secret key `configs/<name>.json`，
      挂载 `/app/data/configs/<name>.json`（subPath，沿用现有 config.json 模式）
    - cronjob args：`uv run horizon --all --date "$D" --notify`（保留 `chmod -R a+rX`）
    - chart README 增加多 config 示例（两套 config、两个 webhook 的 values 片段）

**验收**：`helm upgrade` 后，viewer 首页能列出两套 config 的日报（分 config/语言 chip），
点击可读；卡片按钮直链可达；nginx 仍拒绝 `/summaries/config.json` 等敏感路径。

### Phase 4：文档 / 示例 / 迁移

11. `.env.example`：
    ```
    # 每套 config 一个 webhook（约定 HORIZON_TEAMS_WEBHOOK_URL_<NAME>）
    HORIZON_TEAMS_WEBHOOK_URL_A=https://...
    HORIZON_TEAMS_WEBHOOK_URL_B=https://...
    ```
12. `data/config.example.json` + `docs/configuration.md` + README（zh/ja/en 三份）：
    - `teams` 段完整字段说明（enabled/webhook_url_env/viewer_base_url/top/languages）
    - 「多 config」小节：目录约定、`-n`/`--all` 用法、env 命名约定、回填 `--notify` 说明、
      文件布局（summaries/teams 子目录）
13. 迁移说明（现有生产环境）：
    - 现状 = 默认 config + shell 推 JA。迁移路径：
      1. 现 `config.json` 加 `teams: {enabled: true, languages: ["ja"], webhook_url_env: HORIZON_TEAMS_WEBHOOK_URL_JA}`
      2. cronjob 改为 `uv run horizon --all --date "$D" --notify`（或仅 `horizon --date "$D" --notify`）
      3. 删掉 cronjob 里的 `--json`/`--trigger` 两行
    - ZH 如需进 A 群：新增 `data/configs/zh-a.json`（或按业务命名）配 `..._ZH` env，自动纳入 `--all`
14. 现有 `data/config.json.bak-telecom` / `config_bk.json` 提示用户可按新约定整理进 `data/configs/`

### 测试（随各 Phase 提交）

- `tests/test_language_tags.py` 或 models 测试：`teams.enabled/top/languages` 校验（非法 language、top<0）
- `tests/test_teams_card.py`：`build_card(path_prefix=...)` URL 生成（含空前缀回归）
- 新 `tests/test_teams_delivery.py`：
  - env 未设置 → SKIPPED 且不发请求
  - `httpx.post` mock 200/202 → SUCCESS；4xx/5xx/timeout/ConnectError → 对应结果且不 raise
  - `languages` 过滤命中/未命中
- 编排层测试（`tests/test_orchestrator*.py` 现有 fixture 上扩展）：
  - teams 禁用 → 不发；启用+mock post → 每语言发一次；`notify=False`（backfill）不发
- CLI（`tests/test_main.py` / `test_cli.py`）：
  - `-n` 解析（存在/不存在）、`-c` 优先于 `-n`
  - `--all`：多 config 顺序执行、单 config 失败不中断、exit code 语义
  - `--json` 子目录输入 → 子目录输出 + 语言推断正则（平铺回归）
- `tests/test_storage.py`：`save_daily_summary(subdir=...)` 正常写 + 非法 subdir 名拒绝
- viewer：手动验证（无单测基建，Phase 3 验收清单覆盖）

## 风险与注意

1. **成本翻倍**：N 套 config = N 次完整流水线（重复抓取共享源 + N 倍 AI token）。
   `--all` 顺序执行缓解限流，但不省成本。后续可选优化（本期不做）：共享抓取结果缓存、
   按 config 增量过滤。文档中明示。
2. **回填语义**：`--date` 默认 `notify=False`。生产 cron 迁入流水线推送后**必须带 `--notify`**，
   否则静默不发（这是最容易踩的坑，README + cronjob 注释双强调）。
3. **向后兼容**：默认 config（无 name）行为、平铺 summaries、`--json`/`--trigger` 平铺路径、
   现有测试全部不变；`teams.enabled` 默认 False，存量 config 升级后行为不变。
4. **Secret 膨胀**：每套 config 一个 secret key；config 内含 `${VAR}` 引用的既有机制可继续用来
   避免把 URL 等敏感值写进 config。
5. **viewer 安全面**：新增的两段路径正则必须与目录名白名单一致（单段 + 字符集限制），
   防止 `/summaries/../config.json` 类穿越（alias + 严格字符集 + 不启用 `..`）。

## 工作量估算（粗略）

| Phase | 改动面 | 预估 |
|-------|--------|------|
| 1 流水线内推送 | models / teams / orchestrator + 测试 | 0.5–1 天 |
| 2 多 config CLI + 隔离 | storage / main / configs 工具 + 测试 | 0.5–1 天 |
| 3 viewer + helm | app.js / nginx / chart + 手动验证 | 0.5–1 天 |
| 4 文档迁移 | README×3 / docs / .env.example | 0.5 天 |
