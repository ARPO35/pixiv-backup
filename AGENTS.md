# AGENTS.md
# 项目智能助手协作指南

## 目的
- 让自动化代理/协作开发者快速理解仓库目标、约束与工作流程
- 明确可执行与禁止的操作，降低误改与风险

## 项目概述
- 项目名称：Pixiv Backup（IstoreOS/OpenWrt 备份服务）
- 主要功能：备份 Pixiv 收藏与关注列表的图片与元数据
- 部署形态：OpenWrt 包（ipk），提供 LuCI 可视化配置

## 目录结构（关键路径）
- `Makefile`：OpenWrt 包定义
- `.github/workflows/build-openwrt.yml`：CI 构建
- `src/`：源码
- `src/config/pixiv-backup`：UCI 默认配置
- `src/init.d/pixiv-backup`：procd 服务脚本
- `src/hotplug/99-pixiv-backup`：网络恢复热插拔脚本
- `src/luci-app-pixiv-backup/`：LuCI 应用
- `src/pixiv-backup/`：Python 核心

## 构建与运行
- 目标系统：OpenWrt 23.05+
- 语言与依赖：Python 3 + `requests` + `pixivpy3` + `sqlite3`
- LuCI 依赖：`luci-base`
- CLI：`pixiv-backup` 或 `/etc/init.d/pixiv-backup {start|stop|status|test}`

## 配置要点
- Pixiv 用户 ID
- OAuth refresh token（获取方式见 `docs/refresh-token.md`）
- 输出目录（默认 `/mnt/sda1/pixiv-backup`）

## 允许的操作
- 读取与修改 `src/` 及 LuCI 相关文件
- 更新 UCI 结构与配置读取逻辑
- 修复 LuCI CBI 模型渲染错误
- 更新 CI 配置与构建脚本

## 禁止的操作
- 不得在未确认的情况下推送到远程仓库
- 不得改动用户数据目录（如 `/mnt/sda1/pixiv-backup`）
- 不得引入未知来源依赖或闭源组件

## 开发与修复优先级
1. 修复 LuCI CBI 模型的 section 结构错误
2. 保证 UCI 配置读取与 `main.py` 行为一致
3. CI 构建可复现且稳定

## 变更要求
- 变更需简要说明原因与影响面
- 与 LuCI 相关的改动需说明页面影响
- 有破坏性变更需先获得确认
- 每完成一个小功能/小修复必须单独提交一次（不与其他未完成事项混合提交）

## 测试建议
- LuCI 页面可正常渲染
- `/etc/init.d/pixiv-backup test` 可通过
- 日志输出与配置保存正常

## 备注
- 当任务涉及 Pixiv API 或 OAuth 流程时，请优先保证刷新 token 的流程清晰且可复现
- 如需调整目录结构或 UCI schema，请同步更新文档与默认配置
