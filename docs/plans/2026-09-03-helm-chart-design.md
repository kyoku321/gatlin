# Helm Chart 设计：K8s 化部署 Horizon（CronJob + Markdown 展示站）

日期：2026-09-03
状态：已评审（与需求方确认）

## 背景

项目已移除 GitHub Pages（见本次仓库变更）。日报由 `horizon --date <UTC 前一天>` 生成到
`data/summaries/horizon-YYYY-MM-DD-{lang}.md`。目标：一个 Helm chart，包含两个主要资源：

1. **CronJob**：每天运行 `horizon --date $(date -u -d yesterday +%F)`，`data/` 目录通过 PVC 持久化（读写）。
2. **展示 Pod**：nginx Deployment + Ingress，只读展示 `data/summaries/` 下的 Markdown 日报。

## 关键决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| Markdown 渲染 | 方案 A：零构建，nginx 托管静态页 + 浏览器端 `marked` 渲染 | 日报每天动态生成，构建型框架（MkDocs/VitePress）需每日重建，运维复杂；marked 37k★ 浏览器端标准库 |
| 目录列表 | nginx `autoindex_format json`（nginx ≥1.25，alpine 1.27+） | 无需后端 API，前端 fetch JSON 即可 |
| 存储 | 单个 PVC，`ReadWriteMany`，`helm.sh/resource-policy: keep` | CronJob 读写挂载 `/app/data`；Viewer 同 PVC `readOnly: true` 挂载 `/data` |
| 凭证注入 | chart 从 values 渲染 Secret（`stringData`：`env` + `config.json`） | 需求方选择自包含方式；模板内 `required` + `fromJson` 防呆，非法 JSON 安装即报错 |
| Secret 挂载 | subPath：`env` → `/app/.env`（CWD=/app，`load_dotenv()` 可见）；`config.json` → `/app/data/config.json` | subPath 不随 Secret 热更新，但 CronJob 每日新 Pod，天然刷新 |
| `--date` 时区 | 容器内 `date -u -d yesterday +%F`（GNU date） | 源码 `--date` 语义为 UTC 日期，严格对齐 |
| cron 时区 | `timeZone: Asia/Tokyo`（K8s 1.26+ CronJob 字段），默认 `0 4 * * *` | 需求方指定 Tokyo |
| 镜像 | 2 个镜像，仅新增 1 个 Dockerfile | cron 复用仓库根 `Dockerfile`；viewer 新增 `viewer/Dockerfile`（nginx:alpine，marked 本地 vendor，无 CDN 依赖） |
| 安全 | nginx 仅放行 `= /summaries/`（JSON 列表）与 `~* ^/summaries/([^/]+\.md)$`（单段文件名），其余 `/summaries/*` 一律 404 | PVC 内含 `config.json`、`x_cookies_*.json` 等敏感文件，物理不可达 |
| 前端样式 | 从 git 历史恢复旧 Jekyll 站的 sunrise 配色与 `⭐️ N/10` 彩色徽章逻辑 | 复用既有设计 |
| 其他 | 删除 `docker-compose.yml`（已有 K8s，chart 内无 compose 资源） | 需求方确认 |

## 仓库结构

```
helm_chart/
  Chart.yaml
  values.yaml
  README.md                    # 镜像构建 + helm install 步骤
  templates/
    pvc.yaml                   # RWM，keep
    secret.yaml                # env / config.json（values 渲染 + fromJson 校验）
    cronjob.yaml
    viewer-deployment.yaml
    viewer-service.yaml
    viewer-nginx-config.yaml   # ConfigMap → subPath default.conf
    ingress.yaml
viewer/
  Dockerfile                   # nginx:alpine
  index.html / app.js / styles.css
  vendor/marked.min.js         # 提交进仓库，构建不依赖外网
```

命名约定对齐参考 chart（`/Users/kyoku/Documents/GCC/niuma/helm_chart`）：
`{{ .Release.Name }}-<component>`，`app` 标签，PVC `helm.sh/resource-policy: keep`，
ingress `hosts[].paths[]` + `tls` 结构照搬。

## values.yaml（默认值）

```yaml
cron:
  image:
    repository: core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin
    tag: "latest"
    pullPolicy: Always          # latest 可变，对齐参考 chart
  schedule: "0 4 * * *"
  timeZone: "Asia/Tokyo"
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  resources:
    requests: { memory: 512Mi, cpu: 250m }
    limits:   { memory: 1Gi,  cpu: "1" }

viewer:
  image:
    repository: core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin-viewer
    tag: "latest"
    pullPolicy: Always
  replicaCount: 1
  containerPort: 80
  resources:
    requests: { memory: 64Mi,  cpu: 50m }
    limits:   { memory: 128Mi, cpu: 200m }

persistence:
  storageClass: "basic"
  size: 5Gi
  accessModes: [ReadWriteMany]

ingress:
  enabled: true
  className: nginx
  annotations: {}
  hosts:
    - host: gatlin.gpu-k8s.cloudcore-tu.net
      paths:
        - path: /
          pathType: Prefix
  tls: []

secrets:
  env: |          # 粘贴 .env 全文
  configJson: |   # 粘贴 data/config.json 全文
```

## 数据流

```
PVC (data)  ←RW──  CronJob      /app/data     写 data/summaries/、seen.json 等
   │
   └────RO──────  Viewer Pod    /data         nginx 仅 alias /data/summaries
```

## 模板要点

### CronJob
- `concurrencyPolicy: Forbid`；Job `backoffLimit: 2`，`restartPolicy: OnFailure`
- 覆盖镜像 ENTRYPOINT：`command: ["/bin/sh","-c"]`，`args: ["uv run horizon --date \"$(date -u -d yesterday +%F)\""]`（WORKDIR=/app）
- volumes：PVC → `/app/data`；Secret subPath → `/app/.env`、`/app/data/config.json`

### Viewer
- Deployment 结构对齐参考 frontend-deployment；PVC `readOnly: true` 挂 `/data`
- 默认 RollingUpdate（RWM 无需 Recreate）
- ConfigMap `default.conf`（subPath 挂载）：

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / { try_files $uri $uri/ /index.html; }

    location = /summaries/ {
        alias /data/summaries/;
        autoindex on;
        autoindex_format json;
    }

    location ~* ^/summaries/([^/]+\.md)$ {
        alias /data/summaries/$1;
        default_type text/markdown;
        charset utf-8;
    }

    location /summaries/ { return 404; }
}
```

### Ingress
照抄参考结构，service → `{{ .Release.Name }}-viewer`，`port.number: {{ .Values.viewer.containerPort }}`。

## 前端页面逻辑（viewer/index.html，单文件 SPA 无框架）

1. `fetch('/summaries/')` → JSON → 解析文件名 `horizon-YYYY-MM-DD-{lang}.md` → 按日期倒序列表，日期下显示语言 chip
2. 点击 → `fetch` 原文 → `marked.parse()` → 渲染 `#content`；hash 路由 `#/文件名` 可分享
3. 样式：git 历史中旧 `horizon.css` sunrise 配色；`⭐️ N/10` → 彩色徽章（旧 `horizon.js` 正则逻辑）；CJK 系统字体栈
4. marked 保留 HTML 输出（日报锚点 `<a id=...>` 需要）；内容为自生成，不加 DOMPurify

## 镜像构建

```bash
docker build -t core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin:latest .
docker build -t core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin-viewer:latest viewer/
```

## 验证

1. `helm lint` + `helm template`（渲染无错；空/非法 `configJson` 安装即失败）
2. 本地 docker 冒烟：`docker run -p 8080:80 -v $PWD/data:/data:ro .../gatlin-viewer:latest`，浏览器验证列表与渲染
3. 集群：`helm install` → 手动触发 cron（`kubectl create job --from=cronjob/...`）→ logs 确认生成 → 页面出现内容 → 验证 `/summaries/config.json` 返回 404

## 已知边界

- PVC 初始为空，首跑前页面显示"暂无内容"；文档提供手动触发/backfill 方法
- `marked.min.js` 升级 = 重新 vendor + 重建镜像
- 展示站为内网工具，未做认证（Ingress 层如需保护由用户自行加 annotation/网关策略）
