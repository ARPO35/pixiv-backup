# Pixiv备份服务 for OpenWrt/IstoreOS

一个用于OpenWrt/IstoreOS的Pixiv备份服务，支持通过LuCI界面配置，自动备份用户的收藏和关注列表。

## 功能特点

- 📱 **LuCI界面**: 完整的Web配置界面
- 🔐 **Pixiv API认证**: 支持 OAuth refresh token
- 📸 **原图优先下载**: 单图/多图按原图链接优先下载
- 📋 **元数据保存**: 保存完整的作品信息
- 🔄 **巡检与冷却**: 支持巡检间隔、达到上限冷却、错误冷却
- ⚡ **立即备份触发**: LuCI 可跳过当前等待立即开始新一轮
- 📊 **运行状态**: 显示当前状态、处理进度、冷却信息、最近错误
- 🔄 **断点续传**: 支持从上次中断处继续下载

## 安装方法

### 1. 直接安装（预编译包，推荐）

```bash
# 下载安装包
wget https://github.com/ARPO35/pixiv-backup/releases/download/v1.0.0/pixiv-backup_1.0.0-1_all.ipk
wget https://github.com/ARPO35/pixiv-backup/releases/download/v1.0.0/luci-app-pixiv-backup_1.0.0-1_all.ipk

# 安装
opkg install pixiv-backup_1.0.0-1_all.ipk
opkg install luci-app-pixiv-backup_1.0.0-1_all.ipk
```

### 2. GitHub Actions 自动编译

本项目支持使用 GitHub Actions 自动编译 OpenWrt 包，无需本地配置编译环境。

#### 使用方法：

**方法 A：自动触发编译**
1. Fork 本仓库到你的 GitHub 账号
2. 推送代码到 `main` 或 `master` 分支
3. 在 GitHub 仓库的 "Actions" 页面查看编译进度
4. 编译完成后，在 Artifacts 中下载 `.ipk` 文件

**方法 B：手动触发编译**
1. 进入 GitHub 仓库的 "Actions" 页面
2. 选择 "Build OpenWrt Package" 工作流
3. 点击 "Run workflow" 按钮
4. 选择分支并运行

**方法 C：创建 Release**
```bash
# 创建并推送标签
git tag v1.0.0
git push origin v1.0.0
```
GitHub Actions 会自动编译并创建 Release，IPK 文件会附加到 Release 中。

详细说明请查看：[`.github/workflows/README.md`](.github/workflows/README.md)

### 3. 本地编译（需要 OpenWrt SDK）

```bash
# 克隆代码
git clone https://github.com/ARPO35/pixiv-backup.git

# 将项目复制到 OpenWrt SDK 的 package 目录
cp -r pixiv-backup /path/to/openwrt-sdk/package/

# 进入 OpenWrt SDK 目录
cd /path/to/openwrt-sdk

# 配置编译选项
make menuconfig  # 选择 Utilities -> pixiv-backup, LuCI -> Applications -> luci-app-pixiv-backup

# 编译
make package/pixiv-backup/compile V=s

# 安装
opkg install bin/packages/*/pixiv-backup*.ipk
opkg install bin/packages/*/luci-app-pixiv-backup*.ipk
```

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
   - **巡检与冷却参数**: 巡检间隔、冷却时间、高低速队列

4. 点击"保存&应用"

### 3. 启动服务

在LuCI界面中：
1. 确保配置正确
2. 点击"启用服务"并保存
3. 需要立即执行时点击"立即开始备份"

或者使用命令行：
```bash
# 测试配置
/etc/init.d/pixiv-backup test

# 启动服务
/etc/init.d/pixiv-backup start

# 查看状态
/etc/init.d/pixiv-backup status
```

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
  "bookmark_count": job_id,
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
  "original_url": "https://www.pixiv.net/artworks/12345678"
}
```

## 命令行工具

### 手动运行备份
```bash
pixiv-backup run 20
```
说明：`run` 模式必须指定本次下载数量。

### 只读查看状态
```bash
pixiv-backup status
```

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

### 守护进程模式
```bash
pixiv-backup --daemon
```
说明：daemon 模式按配置巡检并使用 `max_downloads` 作为每轮上限。

### Refresh Token 获取说明
```bash
cat /usr/share/doc/pixiv-backup/refresh-token.md
```

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
   - 若出现网络/限速错误，服务会按错误冷却策略等待后重试

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
