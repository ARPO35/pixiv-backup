# Pixiv Backup 前端读取数据规范

本文档面向“读取本地备份文件并展示”的前端项目，说明 `output_dir` 下目录结构、`metadata/*.json` 格式、运行状态文件与日志格式。

## 1. 作用范围

- 适用版本：当前 `main` 分支（`img/<illust_id>/` + `metadata/<illust_id>.json` 结构）。
- 数据根目录：UCI 配置项 `output_dir`，默认 `/mnt/sda1/pixiv-backup`。
- 重点对象：
  - 图片文件：`img/`
  - 元数据：`metadata/`
  - 运行状态与日志：`data/status.json`、`data/logs/`
  - 可选统计源：`data/pixiv.db`

## 2. 根目录结构

```text
<output_dir>/
├── img/                        # 图片文件（按作品ID分目录）
│   └── <illust_id>/
│       ├── <illust_id>.<ext>           # 单图
│       ├── <illust_id>.p0.<ext>        # 多图第0页
│       ├── <illust_id>.p1.<ext>        # 多图第1页
│       └── <illust_id>.zip             # 动图(ugoira)ZIP
├── metadata/
│   └── <illust_id>.json
└── data/
    ├── pixiv.db                # SQLite（可选读取）
    ├── task_queue.json         # 扫描构建的下载任务队列
    ├── scan_cursor.json        # 扫描游标（收藏/关注增量断点）
    ├── status.json             # 运行态
    ├── last_run.txt            # 最后完成时间（可选）
    ├── run_history.json        # 运行历史（可选）
    ├── force_run.flag          # 立即触发标志
    ├── token.json              # token缓存（敏感，不建议前端暴露）
    ├── cache/
    ├── thumbnails/
    └── logs/
        └── pixiv-backup-YYYYMMDD.log
```

说明：

- `run_history.json`/`last_run.txt` 只在某些运行路径会生成，不保证始终存在。
- 文件系统中可能出现“目录已创建但文件未齐全”（下载中断、网络失败）。

## 3. 图片文件命名规则

## 3.1 静态单图

- 路径：`img/<illust_id>/<illust_id>.<ext>`
- 示例：`img/12345678/12345678.jpg`

## 3.2 静态多图

- 路径：`img/<illust_id>/<illust_id>.p<page_index>.<ext>`
- 示例：`img/101612396/101612396.p0.jpg`

## 3.3 动图（ugoira）

- 路径：`img/<illust_id>/<illust_id>.zip`
- 示例：`img/99999999/99999999.zip`

## 3.4 扩展名来源

- 扩展名从 Pixiv 原始 URL 解析，常见 `jpg/png/webp`。
- 前端不要假设固定后缀，应按实际文件或 MIME 检测。

## 4. metadata JSON 规范

每个作品对应 `metadata/<illust_id>.json`，UTF-8 编码，`ensure_ascii=false`。

## 4.1 字段清单

| 字段 | 类型 | 说明 |
|---|---|---|
| `illust_id` | number | 作品 ID（主键） |
| `title` | string | 标题 |
| `caption` | string | 描述（可能为空，可能包含 HTML 片段） |
| `user.user_id` | number | 作者 ID |
| `user.name` | string | 作者名称 |
| `user.account` | string | 作者账号 |
| `user.profile_image_url` | string | 作者头像 URL |
| `create_date` | string | 作品创建时间（ISO 8601，含时区） |
| `page_count` | number | 页数（多图数量） |
| `width` | number | 宽度（通常为封面页尺寸） |
| `height` | number | 高度（通常为封面页尺寸） |
| `bookmark_count` | number | 收藏数 |
| `view_count` | number | 浏览数 |
| `sanity_level` | number | 内容分级（Pixiv原始字段） |
| `x_restrict` | number | 限制级别（Pixiv原始字段） |
| `type` | string | 作品类型，如 `illust` / `manga` / `ugoira` |
| `tags` | string[] | 标签数组（仅标签名） |
| `image_urls` | object | Pixiv返回的预览图 URL 集（通常包含 `medium/large/square_medium`） |
| `tools` | string[] | 使用工具 |
| `download_time` | string | 本地下载时间（`YYYY-MM-DD HH:mm:ss`） |
| `original_url` | string | 作品页 URL（`https://www.pixiv.net/artworks/<id>`） |
| `is_bookmarked` | boolean | 是否来自收藏扫描 |
| `is_following_author` | boolean | 是否来自关注作者扫描 |
| `bookmark_order` | number \| null | 收藏顺序号（最旧为 0，越新越大；非收藏来源可能为 `null`） |
| `is_access_limited` | boolean | 是否为访问受限占位资源（如 `limit_unknown`） |

## 4.2 真实样例（节选）

```json
{
  "illust_id": 101612396,
  "title": "けもみみメイドが家にいる23",
  "caption": "",
  "user": {
    "user_id": 176236,
    "name": "さわやか鮫肌",
    "account": "tokuoka",
    "profile_image_url": "https://i.pximg.net/user-profile/...jpg"
  },
  "create_date": "2022-10-01T18:44:16+09:00",
  "page_count": 7,
  "type": "manga",
  "tags": ["漫画", "オリジナル"],
  "image_urls": {
    "square_medium": "https://i.pximg.net/...",
    "medium": "https://i.pximg.net/...",
    "large": "https://i.pximg.net/..."
  },
  "download_time": "2026-02-08 01:52:50",
  "original_url": "https://www.pixiv.net/artworks/101612396",
  "is_access_limited": false
}
```

## 4.3 前端处理建议

- 以 `illust_id` 作为唯一键，避免用标题或文件名去重。
- 展示图片时优先读取本地 `img/<id>/`，不要依赖 `image_urls`（那是远端 URL）。
- `page_count` 是理论页数，不等于本地实际下载文件数；请以文件系统结果为准。
- `caption` 可能含 HTML，渲染前请做 XSS 处理或转纯文本。
- 时间字段建议统一转换为本地时区展示。
- 若 `is_access_limited=true`，该作品应从默认画廊主流中排除（通常显示到“异常/受限”分组）。
- 收藏页建议优先按 `bookmark_order DESC` 排序（最新收藏在前）；当 `bookmark_order` 为空时可回退 `create_date DESC`。

## 5. 运行状态文件（status.json）

路径：`data/status.json`

常见字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `state` | string | 运行状态：如 `idle` / `syncing` / `cooldown` |
| `phase` | string | 当前阶段：如 `start/bookmarks/following/done/error/waiting` |
| `message` | string | 人类可读描述 |
| `processed_total` | number | 本轮处理总作品数 |
| `success` | number | 成功数 |
| `skipped` | number | 跳过数 |
| `failed` | number | 失败数 |
| `hit_max_downloads` | boolean | 是否触达本轮上限 |
| `rate_limited` | boolean | 是否识别为限速/服务异常 |
| `last_error` | string \| null | 最近错误 |
| `queue_pending` | number | 队列中 pending 数 |
| `queue_running` | number | 队列中 running 数 |
| `queue_failed` | number | 队列中 failed 数 |
| `queue_permanent_failed` | number | 队列中 permanent_failed 数 |
| `queue_done` | number | 队列中 done 数 |
| `last_run` | string | 最近完成时间 |
| `cooldown_reason` | string | 冷却原因（仅 `cooldown` 状态） |
| `next_run_at` | string | 下次巡检时间（仅 `cooldown` 状态） |
| `cooldown_seconds` | number | 剩余/总冷却秒数（仅 `cooldown` 状态） |
| `updated_at` | string | 文件更新时间 |

说明：

- 字段是“增量更新”的，不保证每次都齐全。
- 前端应按可选字段处理，避免强依赖某个 phase 专属字段。

## 6. 日志文件规范

路径：`data/logs/pixiv-backup-YYYYMMDD.log`

常规 Python 日志格式：

```text
YYYY-MM-DD HH:MM:SS,mmm - <logger> - <LEVEL> - <message>
```

LuCI 操作审计行（结构化）：

```text
YYYY-MM-DD HH:MM:SS - pixiv-backup.audit - INFO - event=luci_action source=<controller|cbi> action=<start|stop|...> status=<ok|error> ip=<ip> ua=<ua> detail=<detail>
```

前端如果需要“操作流水”，建议按 `pixiv-backup.audit` 过滤。

## 7. SQLite 数据（可选）

路径：`data/pixiv.db`

主要表：

- `users`
- `illusts`
- `download_history`

用途建议：

- 前端只读统计可用；核心展示仍建议以 `metadata/*.json + img/` 为主，避免数据库 schema 演化带来的兼容问题。
- 不建议仅依赖 `illusts.downloaded=1` 作为“可展示”判断，需同时过滤 `is_access_limited=true`。

## 8. 兼容性与历史迁移

- 当前版本使用按作品 ID 的平铺元数据：`metadata/<illust_id>.json`。
- 当前开发阶段默认不兼容旧历史结构，前端按现行 schema 开发即可。

## 8.1 任务队列（task_queue.json）

路径：`data/task_queue.json`

```json
{
  "version": 1,
  "updated_at": "2026-02-08 12:00:00",
  "items": [
    {
      "illust_id": 12345678,
      "status": "pending",
      "retry_count": 0,
      "failed_rounds": 0,
      "last_error": null,
      "error_category": null,
      "http_status": null,
      "next_retry_at": null,
      "is_bookmarked": true,
      "is_following_author": false,
      "enqueued_at": "2026-02-08 12:00:00",
      "updated_at": "2026-02-08 12:00:00",
      "illust": { "...": "Pixiv 原始作品对象（裁剪后）" }
    }
  ]
}
```

说明：

- `status` 取值：`pending` / `running` / `done` / `failed` / `permanent_failed`。
- `error_category` 取值：`invalid` / `rate_limit` / `network` / `auth` / `unknown`。
- `failed` 任务会按 `next_retry_at` 延后重试。
- `permanent_failed` 表示自动重试已终止（当前策略：失效作品连续失败达到阈值）。
- 前端可基于该文件展示“排队中/失败重试中”状态。

## 8.2 扫描游标（scan_cursor.json）

路径：`data/scan_cursor.json`

```json
{
  "version": 1,
  "updated_at": "2026-02-08 12:00:00",
  "bookmarks": {
    "full_scan": false,
    "incremental_stopped": true,
    "latest_seen_illust_id": 12345678,
    "latest_seen_create_date": "2026-02-08T11:00:00+09:00",
    "updated_at": "2026-02-08 12:00:00"
  },
  "following": {
    "authors": {
      "55486255": {
        "latest_seen_illust_id": 138914837,
        "latest_seen_create_date": "2026-02-08T10:20:00+09:00",
        "updated_at": "2026-02-08 12:00:00"
      }
    }
  }
}
```

说明：

- 收藏采用“连续已存在阈值”增量停止时，会刷新 `bookmarks` 游标信息。
- 关注采用“按作者游标”增量；若检测作者返回顺序异常，该作者会自动回退全量扫描。

## 9. 前端实现建议（最小读取流程）

1. 读取 `metadata/` 目录，建立 `illust_id -> metadata` 索引。
2. 对每个 `illust_id` 扫描 `img/<illust_id>/`，建立本地文件列表。
3. 列表页优先显示每个作品的首张本地图片（存在 `p0` 时优先 `p0`）。
4. 详情页显示 metadata 字段，并按本地文件顺序展示所有页。
5. 状态栏读取 `data/status.json` + `pixiv-backup.audit` 日志显示运行态与操作记录。

默认筛选建议（避免受限占位图进入主流）：

- 列表默认条件：`downloaded=true AND is_access_limited!=true`。
- 如需排障页，再单独展示 `is_access_limited=true` 作品。

收藏排序建议：

- 主排序：`bookmark_order DESC`（最新收藏优先）。
- 回退排序：`create_date DESC`。
- 若做前端索引缓存，建议持久化 `bookmark_order`，不要每次临时按文件修改时间排序。

全量重建索引建议（当规则变更后）：

1. 清理前端自身索引缓存（如 `index.sqlite`/内存快照）。
2. 若历史 metadata 缺少 `bookmark_order`，先运行 `tools/backfill_bookmark_order.py` 回填。
3. 重新全量遍历 `metadata/*.json` 与 `img/` 建索引。
4. 首轮完成后再切回增量监听（`mtime`）。

## 10. 安全注意事项

- 不要在前端泄露 `data/token.json` 内容。
- 不要直接信任 `caption` 的 HTML，必须做净化或转义。
- 若前端提供文件下载，应限制路径穿越（仅允许 `output_dir` 子路径）。
