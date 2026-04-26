# Pixiv备份服务 for OpenWrt/IstoreOS

一个用于OpenWrt/IstoreOS的Pixiv备份服务，支持通过LuCI界面配置，自动备份用户的收藏和关注列表。

## 功能特点

- 📱 **LuCI界面**: 完整的Web配置界面
- 🔐 **Pixiv API认证**: 支持 OAuth refresh token
- 📸 **原图优先下载**: 单图/多图按原图链接优先下载
- 📋 **元数据保存**: 保存完整的作品信息
- 🔄 **巡检与冷却**: 支持巡检间隔、达到上限冷却、错误冷却
- ⚡ **立即备份触发**: LuCI 可跳过当前等待立即开始新一轮
- 📊 **运行状态**: 显示当前状态、处理进度、冷却信息、队列分项、最近10条错误
- 🔄 **断点续传**: 支持从上次中断处继续下载
- 🧭 **错误分类重试**: 区分失效/限速/网络错误，失效作品会进入终态失败

## 配置步骤

### 1. 获取Pixiv Refresh Token

请参考文档：[`docs/refresh-token.md`](docs/refresh-token.md)

### 2. LuCI界面配置

1. 登录LuCI管理界面（通常是 http://192.168.1.1）
2. 进入"服务" -> "Pixiv备份"
3. 配置以下信息：
   - **用户ID**: 你的Pixiv用户ID
   - **Refresh Token**: 上一步获取的refresh_token
   - **输出目录**: 保存图片的目录（默认 /mnt/sda1/pixiv-backup）
   - **下载模式**: 选择要下载的内容（收藏/关注/两者）
   - **巡检与冷却参数**: 巡检间隔、冷却时间、下载间隔随机偏移（毫秒）、高低速队列

4. 点击"保存&应用"

### 3. 启动服务

在LuCI界面中：
1. 确保配置正确
2. 点击"启用服务"并保存
3. 需要立即执行时点击"立即开始备份"

或者使用命令行：
```bash
# 测试配置
pixiv-backup test

# 启动服务
pixiv-backup start

# 查看状态
pixiv-backup status
```

LuCI 实时状态说明：
- **总共已处理**：使用数据库 `illusts.downloaded=1` 的实时数量。
- **队列汇总**：拆分展示 `total/pending/running/failed/permanent_failed/done` 六项。
- **最近错误**：最多显示 10 条，每条两行（时间+PID+操作+URL / 纯错误信息），条目之间有空行分隔。

## 目录结构

服务运行后会在输出目录创建以下结构：

```
/mnt/sda1/pixiv-backup/
├── img/                    # 图片文件（按作品PID分类）
│   ├── {illust_id}/
│   │   ├── {illust_id}.jpg
│   │   ├── {illust_id}.p0.jpg
│   │   └── {illust_id}.zip
│   └── ...
├── metadata/              # 元数据文件
│   ├── {illust_id}.json
│   └── ...
└── data/                  # 程序数据
    ├── pixiv.db          # SQLite数据库
    ├── task_queue.json   # 扫描后待下载任务队列
    ├── cache/            # 缓存文件
    ├── logs/             # 日志文件
    ├── status.json       # 运行状态
    └── force_run.flag    # 立即备份触发标志
```

## 元数据结构

每个作品的元数据文件包含以下信息：

```json
{
  "illust_id": 12345678,
  "title": "作品标题",
  "caption": "作品描述",
  "user": {
    "user_id": 87654321,
    "name": "作者名称",
    "account": "作者账号",
    "profile_image_url": "头像URL"
  },
  "create_date": "2023-01-01T00:00:00+09:00",
  "page_count": 1,
  "width": 1200,
  "height": 800,
  "bookmark_count": 1234,
  "view_count": 5000,
  "sanity_level": 2,
  "x_restrict": 0,
  "type": "illust",
  "tags": ["tag1", "tag2", "tag3"],
  "image_urls": {
    "large": "https://i.pximg.net/...",
    "medium": "https://i.pximg.net/...",
    "square_medium": "https://i.pximg.net/..."
  },
  "tools": ["SAI", "Photoshop"],
  "download_time": "2023-12-01 14:30:00",
  "original_url": "https://www.pixiv.net/artworks/12345678",
  "is_bookmarked": true,
  "is_following_author": false,
  "bookmark_order": 1234,
  "is_access_limited": false
}
```
说明：当前为开发阶段数据结构，默认不做旧 metadata 兼容迁移。
前端默认列表建议过滤 `is_access_limited=true`，避免将 `limit_unknown` 占位资源当作可展示主图。
收藏列表建议优先按 `bookmark_order` 倒序（`DESC`）显示，`bookmark_order` 越大表示收藏越新。

### 收藏序号回填命令（一次性）
当你需要给已有 `metadata/*.json` 批量补齐 `bookmark_order` 时，可运行：
```bash
pixiv-backup bookmark-order --restrict both --progress
```
说明：
- 命令会全量拉取收藏列表（最新在前），按“最旧=0、最新最大”回填 `bookmark_order`。
- 同时会更新 `metadata` 与 `data/task_queue.json` 中的 `is_bookmarked/bookmark_order`。
- 可先加 `--dry-run` 预览变更数量。
- 可加 `--progress` 显示进度，`--debug` 打印前 20 条变更样例。
- 若需包含私密收藏，使用 `--restrict both`（public + private）。

## 命令行工具

### 服务控制（统一入口）
```bash
# 启动后台服务
pixiv-backup start

# 启动并立即触发新一轮（跳过冷却）
pixiv-backup start --force-run

# 停止后台服务
pixiv-backup stop

# 重启后台服务
pixiv-backup restart

# 重启并立即触发新一轮
pixiv-backup restart --force-run

# 仅触发立即扫描（不启动服务）
pixiv-backup trigger

# 执行服务测试（与 init.d test 等价）
pixiv-backup test
```
说明：
- `pixiv-backup trigger` 会输出当前服务状态与预计生效时机（冷却中会在 1-2 秒内跳过等待）。
- 若 LuCI “立即扫描”按钮异常，可直接使用 `pixiv-backup trigger` 触发并查看返回原因。

### 手动运行备份
```bash
pixiv-backup run 20

# 强制全量扫描（跳过增量停止逻辑）
pixiv-backup run 20 --full-scan
```
说明：`run` 模式必须指定本次下载数量。

### 只读查看状态
```bash
pixiv-backup status
```
说明：
- `本轮已处理`：当前/最近一轮处理总数（成功+跳过+失败）。
- `累计成功下载`：数据库 `illusts.downloaded=1` 的实时数量。
- 输出会包含冷却信息、队列六项状态和最近 10 条错误（每条两行，第一行含 URL，第二行仅错误信息）。

### 诊断与修复
```bash
# 检查并按提示修复（非交互环境默认自动修复）
pixiv-backup repair

# 仅检查，不修复
pixiv-backup repair --check

# 直接修复（跳过询问）
pixiv-backup repair --apply -y
```
说明：
- `--check` 与 `--apply` 不能同时使用。
- 仅检查发现问题时会返回非 0。

### 一键重排收藏顺序
```bash
# 重新拉取收藏并重排 metadata/task_queue 的 bookmark_order（默认 both）
pixiv-backup bookmark-order

# 仅预览，不写入文件
pixiv-backup bookmark-order --dry-run

# 指定范围（public/private/both）
pixiv-backup bookmark-order --restrict both
```
说明：
- 默认按 `--restrict both` 拉取 public + private 收藏，重排规则为“最旧=0、最新最大”。
- 若后台守护进程正在运行，命令会先自动执行 `stop`，并且本次不会自动重启服务。
- 当条目未命中本次收藏结果时，会保留原有 `is_bookmarked/bookmark_order`，仅输出告警统计。
- 若收藏拉取过程失败（如限速/网络异常），命令会直接失败并且不落盘。

### 持续查看服务日志
```bash
# 默认先输出最近100行，然后持续追踪（Ctrl+C退出）
pixiv-backup log

# 只看最近20行后退出
pixiv-backup log --no-follow -n 20

# 强制读取文件日志
pixiv-backup log --file

# 强制读取系统日志
pixiv-backup log --syslog
```
说明：
- `--file` 与 `--syslog` 不能同时使用，同时指定会报参数错误并退出。
- 未指定来源参数时会自动选择：优先文件日志，缺失时回退到 `logread`。
- 跟随模式下若日志文件被删除，会提示一次并等待新日志文件，不会重复回放旧日志。

### 查看未处理报错
```bash
# 查看最新50条未处理报错（默认）
pixiv-backup errors

# 仅看最近20条
pixiv-backup errors -n 20

# JSON输出（便于脚本处理）
pixiv-backup errors --json
```
说明：
- “未处理”口径：按每个作品最新失败记录判断，且当前 `illusts.downloaded=0`。

### 守护进程模式
```bash
pixiv-backup --daemon
```
说明：`--daemon` 为兼容入口，正常服务管理推荐使用 `pixiv-backup start/stop/restart`。

### Refresh Token 获取说明
```bash
cat /usr/share/doc/pixiv-backup/refresh-token.md
```

### 前端读取规范
- 备份目录与 metadata 格式详见：[`docs/frontend-data-spec.md`](docs/frontend-data-spec.md)

## 故障排除

### 常见问题

1. **认证失败**
   - 检查refresh_token是否正确
   - 确保token没有过期或被撤销
   - 尝试重新获取token

2. **连接失败**
   - 检查网络连接
   - 检查上游网络是否可访问 Pixiv OAuth/API 域名
   - 检查Pixiv API是否可用

3. **下载中断**
   - 检查磁盘空间
   - 查看日志目录 `/mnt/sda1/pixiv-backup/data/logs/`
   - `429/5xx` 会按限速/服务异常处理并进入错误冷却
   - 网络类错误会自动重试
   - `404/410/作品失效` 会在达到重试阈值后标记为 `permanent_failed`

4. **LuCI界面不显示**
   - 确保安装了luci-app-pixiv-backup
   - 检查LuCI主题兼容性
   - 清除浏览器缓存

### 日志查看

```bash
# 推荐：通过命令持续查看（默认先回看100行再追踪）
pixiv-backup log

# 仅快照查看最近50行
pixiv-backup log --no-follow -n 50

# 强制从系统日志读取
pixiv-backup log --syslog

# 仅查看LuCI操作审计日志（start/stop/配置提交等）
pixiv-backup log | grep "pixiv-backup.audit"

# 在LuCI界面查看日志
# 进入"服务" -> "Pixiv备份" -> "日志"
```

## 开发说明

### 项目结构
```
pixiv-backup/
├── Makefile                    # OpenWrt包构建文件
├── src/
│   ├── luci-app-pixiv-backup/  # LuCI界面
│   │   ├── luasrc/
│   │   │   ├── controller/     # 控制器
│   │   │   ├── model/cbi/      # CBI配置文件
│   │   │   └── view/          # 视图模板
│   │   └── htdocs/            # 静态资源
│   ├── pixiv-backup/          # Python主程序
│   │   ├── main.py
│   │   ├── modules/           # 核心模块
│   │   ├── tools/             # 辅助模块
│   │   └── requirements.txt   # Python依赖
│   ├── init.d/               # init脚本
│   └── config/               # 配置文件模板
└── README.md                 # 本文档
```

### 修改配置

配置文件位于 `/etc/config/pixiv-backup`，可以使用uci命令修改：

```bash
# 查看配置
uci show pixiv-backup

# 修改配置
uci set pixiv-backup.settings.user_id='123456'
uci set pixiv-backup.settings.enabled='1'
uci set pixiv-backup.settings.sync_interval_minutes='360'
uci set pixiv-backup.settings.max_downloads='1000'
uci commit pixiv-backup
```

## 许可证

本项目采用 GPL-3.0 许可证开源。

## 支持与反馈

- 问题反馈: [GitHub Issues](https://github.com/ARPO35/pixiv-backup/issues)
- 功能建议: [GitHub Discussions](https://github.com/ARPO35/pixiv-backup/discussions)

## 注意事项

1. **尊重版权**: 仅用于个人收藏，请勿用于商业用途
2. **遵守条款**: 遵守Pixiv服务条款
3. **合理使用**: 避免对Pixiv服务器造成过大压力
4. **隐私保护**: 妥善保管你的refresh_token
