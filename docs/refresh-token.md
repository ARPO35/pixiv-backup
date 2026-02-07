# Pixiv Refresh Token 获取指南

本项目不再提供内置 token 获取脚本。  
当前建议使用 `gppt` 工具获取 `refresh_token`，然后在 LuCI 中填写。

## 1. 在电脑上获取 refresh_token（推荐）

1. 安装 Python 包：

```bash
pip install gppt
```

2. 查看帮助确认命令可用：

```bash
gppt -h
```

3. 交互式登录获取 token（会拉起浏览器）：

```bash
gppt login
```

4. 成功后输出中会包含：
- `access_token`
- `refresh_token`
- `expires_in`

请复制并保存 `refresh_token`。

## 2. 填写到 OpenWrt

1. 打开 LuCI：`服务 -> Pixiv备份`
2. 填写：
- `Pixiv用户ID`
- `Refresh Token`
3. 点击“保存并应用”

## 3. 可选：校验 token 是否可用

在任意 Python 环境中执行：

```python
from pixivpy3 import AppPixivAPI

api = AppPixivAPI()
api.auth(refresh_token="你的refresh_token")
print("auth ok")
```

如果报错，请重新获取新的 `refresh_token`。

## 常见问题

- `gppt` 命令不存在：确认已在当前 Python 环境安装 `gppt`，或改用 `python -m gppt -h`。
- 登录后未返回 token：检查网络连通性和代理设置。`gppt` 文档建议可使用 `ALL_PROXY` 或 `HTTPS_PROXY` 环境变量。
- token 失效：在 Pixiv 侧撤销旧授权后重新登录获取。

## 安全提示

- `refresh_token` 属于高敏感凭据，请勿公开或提交到仓库。
- 建议仅在可信设备上获取和存储 token。
