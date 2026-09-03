# gatlin Helm Chart

在 Kubernetes 上部署 Gatlin（Horizon）日报系统，包含两个主要资源：

1. **CronJob** — 每天运行 `horizon --date <UTC 前一天>`，日报写入 PVC 上的 `data/summaries/`
2. **Viewer** — nginx Deployment + Ingress，只读展示 `data/summaries/` 下的 Markdown 日报

设计文档：[`docs/plans/2026-09-03-helm-chart-design.md`](../docs/plans/2026-09-03-helm-chart-design.md)

## 前置条件

- Kubernetes **1.26+**（CronJob `timeZone` 字段）
- 支持 **ReadWriteMany** 的 StorageClass（默认 `basic`）
- Ingress Controller（默认 `nginx`）
- 已构建并推送两个镜像到 Harbor：

```bash
# cron 镜像（仓库根 Dockerfile）
docker buildx build \
  --platform=linux/amd64 \
  --file Dockerfile -t core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin:latest .

# viewer 镜像（viewer/ 目录，marked 已 vendor，构建不需要外网）
docker buildx build \
  --platform=linux/amd64 \
  --file Dockerfile -t core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin-viewer:latest viewer/

docker push core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin:latest
docker push core.harbor.cloudcore-tu.net/aggpf/gatlin/gatlin-viewer:latest
```

## 安装

1. 准备 values 文件，把真实配置填进 `secrets`：

```yaml
secrets:
  # 你的 .env 全文（API key、SMTP、webhook 等）
  env: |
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=...
  # 你的 data/config.json 全文（可参考仓库 data/config.example.json）
  configJson: |
    { "ai": { ... } }
```

> `configJson` 会在 `helm install` 时做 JSON 校验，非法 JSON 直接安装失败。
> `secrets.env` 为空时安装成功但 cron 会跑失败，NOTES 会打印警告。

2. 安装 / 升级：

```bash
# 首次安装
helm install gatlin ./helm_chart -n gatlin --create-namespace -f my-values.yaml

# 后续升级（values 或 chart 有变更时）
helm upgrade gatlin ./helm_chart -n gatlin -f my-values.yaml

# 推送新镜像后，让 viewer 拉取新 latest（cron 每次运行都是新 Pod，无需操作）
kubectl -n gatlin rollout restart deployment/gatlin-viewer
```

3. 手动触发首次运行（PVC 初始为空，页面会显示"暂无内容"）：

```bash
kubectl -n gatlin create job --from=cronjob/gatlin-cron gatlin-cron-manual-1
kubectl -n gatlin logs -f job/gatlin-cron-manual-1
```

跑完后日报出现在 viewer 页面上。

## 主要 values

| Key | 默认值 | 说明 |
|-----|--------|------|
| `cron.schedule` | `"0 4 * * *"` | 每天运行时间 |
| `cron.timeZone` | `Asia/Tokyo` | schedule 时区（K8s 1.26+） |
| `persistence.storageClass` | `basic` | 需支持 ReadWriteMany |
| `persistence.size` | `5Gi` | 日报 + seen.json 等状态数据 |
| `ingress.hosts` | — | 展示站域名 |
| `secrets.env` | 空 | `.env` 全文 → 挂载到 `/app/.env` |
| `secrets.configJson` | `{}` | `data/config.json` 全文 → 挂载到 `/app/data/config.json` |

## 工作原理

- CronJob 与 Viewer 共享同一个 PVC（`ReadWriteMany`，`helm.sh/resource-policy: keep`）
- CronJob 读写挂载到 `/app/data`；Viewer **只读**挂载到 `/data`
- nginx 仅放行 `/summaries/`（JSON 目录列表）与 `/summaries/<单段文件名>.md`，
  PVC 里的 `config.json`、`x_cookies_*.json` 等文件物理不可达
- 页面为单文件 SPA：`fetch` 目录列表 → 按日期×语言分组 → 点击用浏览器端 marked 渲染
- `--date` 取 `date -u -d yesterday +%F`，与 horizon `--date` 的 UTC 语义一致

## 卸载

```bash
helm uninstall gatlin -n gatlin
# PVC 带 resource-policy: keep，uninstall 不会删除数据；
# 如需彻底清理：kubectl -n gatlin delete pvc gatlin-data
```
