# 审查问题清单

## P1

### 关注作者作品列表需要分页

- 文件：`src/pixiv-backup/modules/crawler.py`
- 位置：约 591-593 行
- 问题：当 `mode=following` 或 `both` 时，针对每个关注作者只调用了一次 `user_illusts()`。如果该作者作品超过接口第一页，后续页面不会被拉取。
- 影响：首次全量同步和 `--full-scan` 都可能永久漏掉关注作者第二页及之后的作品。
- 建议修复：像收藏列表和关注用户列表一样消费返回的 `next_url`，完整分页获取关注作者作品。

### 停止 procd 服务时应使用服务名

- 文件：`src/init.d/pixiv-backup`
- 位置：约 60-62 行
- 问题：`procd_kill` 传入的是可执行文件路径，而不是 procd 服务名和实例名。
- 影响：执行 `/etc/init.d/pixiv-backup stop` 或 `restart` 时可能显示已停止，但旧守护进程仍在运行；随后 `restart` 会启动第二个 daemon。
- 建议修复：按 procd 注册的服务名和实例名调用 `procd_kill`。

## P2

### 将 pixivpy3 打包为依赖，避免启动时 pip 安装

- 文件：`Makefile`
- 位置：包依赖定义
- 问题：包依赖中没有 `pixivpy3`，init 脚本在服务启动时临时执行 `pip3 install pixivpy3`。
- 影响：OECT/IStoreOS/OpenWrt 设备安装 IPK 后不一定有外网、pip 源或编译环境，可能出现安装成功但服务离线启动失败，也会破坏部署可复现性。
- 建议修复：将 `pixivpy3` 纳入可安装的 OpenWrt 包依赖或随包提供，避免运行时依赖 pip 和网络。

### LuCI 点击开始备份时应启动 daemon

- 文件：`src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua`
- 位置：约 320-322 行
- 问题：LuCI 的“开始备份/立即开始备份”入口只执行 `pixiv-backup trigger`。
- 影响：当服务未运行时，该命令只写入 `force_run.flag` 并返回成功提示，实际不会开始备份。
- 建议修复：LuCI 触发备份时应确保 daemon 已启动，必要时先启动或重启服务再触发。

### LuCI 拼接 shell 路径时应使用 shellquote

- 文件：`src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua`
- 位置：约 183-184 行，以及其他日志/路径相关 shell 命令
- 问题：`output_dir` 等来自 UCI 的路径被手工拼接进 shell 命令，并仅用单引号包裹。
- 影响：路径包含单引号或 shell 元字符时，命令可能被截断或注入额外命令。
- 建议修复：凡是从配置拼接到 shell 命令的完整路径参数，都使用 `util.shellquote()` 引用。

### LuCI 需要兼容旧版 main 配置段

- 文件：`src/luci-app-pixiv-backup/luasrc/controller/pixiv-backup.lua`
- 位置：约 146-148 行
- 问题：Python 和 hotplug 逻辑兼容旧版 `pixiv-backup.main.*` 配置段，但 LuCI 状态页只读取 `settings`。
- 影响：从旧配置升级且尚未迁移的设备，会在 LuCI 中显示未配置或默认输出目录；CBI 还可能创建空的 `settings` section，导致页面操作与 daemon 实际读取的配置不一致。
- 建议修复：LuCI 的状态读取和配置读取应复用与 Python/hotplug 一致的旧配置 fallback，或显式迁移旧配置段。

### 重下载失败后应清除 downloaded 状态

- 文件：`src/pixiv-backup/modules/crawler.py`
- 位置：约 1188-1191 行
- 问题：如果某作品曾成功下载、数据库中 `downloaded=1`，但用户后来删除或损坏了图片文件，重新入队后下载失败只会记录错误，不会把 `illusts.downloaded` 清回 `0`。
- 影响：状态统计和未处理错误查询会继续把该作品当作已完成，掩盖实际缺失文件。
- 建议修复：重下载失败时，在记录错误的同时将对应作品的 `downloaded` 状态清为 `0`。

