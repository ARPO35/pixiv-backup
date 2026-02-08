# PROJECT_STATUS.md

## 文档用途
- 用于持续记录本项目的目标、当前状态、核心功能、阶段目标、预计目标与关键修改。
- 作为后续协作与交接的统一事实来源，避免信息分散。

## 1. 项目目的
`pixiv-backup` 是一个运行在 IstoreOS/OpenWrt 上的 Pixiv 自动备份服务，目标是：
- 在路由器侧长期、低干预地同步用户收藏/关注作品。
- 通过 LuCI 提供可视化配置与状态查看。
- 将图片与元数据本地化落盘，支持断点续跑和长期归档。

## 2. 当前产品形态
- 交付形式：OpenWrt `ipk` 包（`pixiv-backup` + `luci-app-pixiv-backup`）。
- 服务管理：`procd`（`/etc/init.d/pixiv-backup`）。
- 核心程序：Python（`/usr/bin/pixiv-backup` -> `src/pixiv-backup/main.py`）。
- 配置系统：UCI（`/etc/config/pixiv-backup`，主 section 为 `settings`）。

## 3. 主要功能（当前有效）
- Pixiv OAuth 刷新令牌鉴权。
- 收藏与关注作品抓取（`mode=bookmarks|following|both`）。
- 原图优先下载（多图逐页下载）。
- 元数据 JSON 保存。
- 后台巡检 + 冷却策略。
- LuCI 一键“立即开始备份”（可跳过当前等待）。
- LuCI 显示运行状态、进度、冷却信息、最近错误原因。

## 4. 已精简/移除功能（当前不再启用）
以下功能已从配置和主流程中移除：
- 定时任务：`schedule_enabled` / `schedule_time`
- 代理：`proxy_enabled` / `proxy_url`
- 过滤：`min_bookmarks` / `r18_mode` / `include_tags` / `exclude_tags`

## 5. 命令行接口（CLI）
入口：`pixiv-backup`

支持命令：
- `pixiv-backup start`
  - 启动后台服务（通过统一 CLI 入口控制服务）。
- `pixiv-backup start --force-run`
  - 启动前写入 `force_run.flag`，用于立即触发新一轮。
- `pixiv-backup stop`
  - 停止后台服务。
- `pixiv-backup restart`
  - 重启后台服务。
- `pixiv-backup test`
  - 执行配置与连接测试（透传 init.d test）。
- `pixiv-backup trigger`
  - 仅触发“跳过冷却并立即扫描”，不负责启动服务。
- `pixiv-backup run <count>`
  - 单次执行，必须传入本次下载数量上限。
  - 示例：`pixiv-backup run 20`
- `pixiv-backup --daemon`
  - 后台巡检循环模式。
  - 每轮上限使用 UCI 的 `max_downloads`。
- `pixiv-backup status`
  - 只读状态输出，不触发下载。
- `pixiv-backup repair`
  - 诊断并修复常见问题（依赖、目录、数据库等）。
  - `--check` 仅检查，不修复。
  - `--apply` 直接执行修复；默认模式下交互询问，非交互环境默认自动修复。
- `pixiv-backup log`
  - 默认先输出最近 100 行日志，再持续追踪（Ctrl+C 退出）。
  - 可选参数：
    - `-n/--lines <N>`：设置快照行数（默认 100）
    - `--no-follow`：只输出快照不追踪
    - `--file`：强制读取文件日志
    - `--syslog`：强制读取系统日志
  - `--file` 与 `--syslog` 互斥，同时指定会报参数错误并退出。
  - 未指定来源参数时按 auto 选择：文件日志优先，缺失时回退 `logread`。

说明：
- `max_downloads` 仅影响 `--daemon` 每轮处理上限。
- `run <count>` 不读取 `max_downloads`，以传参为准。
- `--daemon` 为兼容入口，常规服务管理推荐 `start/stop/restart`。

## 6. init.d 接口
脚本：`src/init.d/pixiv-backup`

支持命令：
- `/etc/init.d/pixiv-backup start`
- `/etc/init.d/pixiv-backup stop`
- `/etc/init.d/pixiv-backup restart`
- `/etc/init.d/pixiv-backup status`
- `/etc/init.d/pixiv-backup test`

实现特性：
- 启动前做依赖检查（`pixivpy3` 自动安装尝试）。
- 启动前校验 UCI 必填项。
- `status` 会读取配置并显示最近日志文件位置。

## 7. LuCI 接口与页面
### 7.1 路由
控制器：`src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua`
- `GET /admin/services/pixiv-backup/status`：返回 JSON 状态
- `GET /admin/services/pixiv-backup/logs`：返回最新日志文本
- `GET /admin/services/pixiv-backup/start`：触发立即备份（调用 `pixiv-backup start --force-run`）
- `GET /admin/services/pixiv-backup/stop`：停止服务

### 7.2 CBI 配置页
模型：`src/luci-app-pixiv-backup/luasrc/model/cbi/pixiv-backup.lua`
- 保存后会根据 `enabled` 执行 `enable/disable`。
- 页面提供“立即开始备份”按钮：
  - 调用 `pixiv-backup start --force-run`

### 7.3 状态数据来源
- 运行态：`output_dir/data/status.json`
- 最近错误：`status.json` 的 `last_error`
- 统计：数据库计数 + 文件系统 `du`

## 8. 配置项（UCI）
文件：`src/config/pixiv-backup`

当前有效配置：
- `enabled`：是否启用服务
- `user_id`：Pixiv 用户 ID
- `refresh_token`：OAuth 刷新令牌
- `output_dir`：输出目录
- `mode`：`bookmarks` / `following` / `both`
- `restrict`：`public` / `private`
- `max_downloads`：daemon 每轮上限
- `timeout`：请求超时
- `sync_interval_minutes`：巡检间隔
- `cooldown_after_limit_minutes`：达到上限冷却
- `cooldown_after_error_minutes`：错误冷却
- `high_speed_queue_size`：高速队列数量
- `low_speed_interval_seconds`：低速队列间隔

## 9. 程序原理（核心运行流程）
核心文件：`src/pixiv-backup/main.py`

### 9.1 daemon 模式循环
1. 执行一轮同步（收藏/关注按 `mode`）。
2. 根据本轮结果选择等待策略：
- 命中限速/服务异常 -> `cooldown_after_error_minutes`
- 达到上限 -> `cooldown_after_limit_minutes`
- 否则 -> `sync_interval_minutes`
3. 等待期间每秒检测 `force_run.flag`：
- 检测到则立即跳过等待，开启下一轮。

### 9.2 单轮同步统计
- 统计口径按“作品数”（illust）计：`success/skipped/failed/total`。
- 文件数量可能大于作品数（多图作品会展开多个文件）。

### 9.3 限速判定策略
在 `crawler` 里使用“关键词 + 状态码文本”判定：
- `rate limit` / `too many requests` / `temporarily unavailable`
- `403/429/500/502/503/504`（消息文本命中）

## 10. 下载与数据结构
### 10.1 图片目录（已改）
- 路径：`img/<illust_pid>/`
- 单图：`<illust_pid>.<ext>`
- 多图：`<illust_pid>.p0.<ext>`, `<illust_pid>.p1.<ext>` ...
- 动图：`<illust_pid>.zip`

### 10.2 元数据目录（已改）
- 路径：`metadata/<illust_pid>.json`

### 10.3 程序数据目录
- `data/pixiv.db`：SQLite
- `data/task_queue.json`：扫描后去重任务队列
- `data/logs/`：日志
- `data/status.json`：运行态
- `data/last_run.txt`：最后运行时间
- `data/force_run.flag`：立即备份触发标志

### 10.4 元数据来源标记
- `metadata/<illust_id>.json` 新增：
  - `is_bookmarked`：是否来自收藏扫描
  - `is_following_author`：是否来自关注作者扫描

### 10.5 当前兼容策略
- 处于开发阶段：默认不做旧数据兼容迁移，按当前 schema 全量重建。

## 11. 数据库与迁移
文件：`src/pixiv-backup/modules/database.py`
- 启动时自动建表。
- 对旧库自动补列（如 `file_size`），避免历史库崩溃。
- `illusts` 使用 upsert，避免重复覆盖时丢失下载状态。

## 12. 关键模块职责
- `modules/config_manager.py`：读取 UCI，兼容 `main/settings`。
- `modules/auth_manager.py`：鉴权、token 缓存、连接测试。
- `modules/crawler.py`：分页抓取、下载调度、限速识别、进度上报。
- `modules/downloader.py`：原图优先下载、文件落盘、元数据写入。
- `modules/database.py`：状态持久化与统计。

## 13. 当前已知问题/风险
1. 网络链路不稳定时，OAuth 可能出现 `SSLEOFError`（环境/链路问题多于业务代码问题）。
2. LuCI 前端模板仍偏简化，状态可视化可继续增强。
3. README 可能存在旧字段说明残留，需持续对齐最新行为。

## 14. 回归验证清单（给下一个 Agent）
### 14.1 设备侧基本验证
```sh
/etc/init.d/pixiv-backup restart
/etc/init.d/pixiv-backup status
pixiv-backup status
pixiv-backup run 5
```

### 14.2 daemon 冷却/强制触发验证
1. 配置较小 `max_downloads`，启动 daemon。
2. 观察进入 `cooldown`。
3. 执行 LuCI“立即开始备份”或手动写标志：
```sh
touch <output_dir>/data/force_run.flag
```
4. 确认等待被跳过并立即开始新一轮。

### 14.3 LuCI 状态验证
- 服务状态与 init.d `running` 一致。
- 本轮进度随下载更新。
- 最近错误仅展示结构化错误原因（`last_error`）。

## 15. 最近提交脉络（便于追溯）
- `ab2ed52`：精简配置并重构 run/daemon 流程
- `c9d48f1`：存储结构改为按作品 PID 归档
- `3d7e620`：修复 LuCI 启动动作与服务状态检测
- `8f53fb7`：巡检/冷却策略 + LuCI 运行状态增强

## 16. 关键文件索引
- `src/config/pixiv-backup`
- `src/init.d/pixiv-backup`
- `src/pixiv-backup/main.py`
- `src/pixiv-backup/modules/config_manager.py`
- `src/pixiv-backup/modules/auth_manager.py`
- `src/pixiv-backup/modules/crawler.py`
- `src/pixiv-backup/modules/downloader.py`
- `src/pixiv-backup/modules/database.py`
- `src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua`
- `src/luci-app-pixiv-backup/luasrc/model/cbi/pixiv-backup.lua`
