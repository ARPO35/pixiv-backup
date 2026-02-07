# Pixiv Refresh Token 获取指南

本项目不再提供内置 token 获取脚本。  
推荐优先使用 `gppt`。如果本机环境不兼容，再使用“F12 + pixiv_auth.py”兜底方案。

## 方案 A：gppt（推荐）

适用条件：
- Python 3.11+（Windows 下推荐 3.11 或 3.12）

步骤：
1. 安装：

```bash
pip install gppt
```

2. 检查命令：

```bash
gppt -h
```

3. 登录获取 token：

```bash
gppt login
```

4. 成功后记录输出中的 `refresh_token`。

## 方案 B：F12 + pixiv_auth.py（兜底）

说明：
- 仅在网页里按 F12 通常拿不到可直接用于 App API 的 `refresh_token`。
- 这个方案的关键是获取 OAuth 回调 URL 里的 `code`，再由 `pixiv_auth.py` 换取 `refresh_token`。

步骤：
1. 下载脚本：

```bash
curl -L -o pixiv_auth.py https://raw.githubusercontent.com/upbit/pixivpy/master/pixiv_auth.py
```

2. 启动登录流程：

```bash
python pixiv_auth.py login
```

3. 浏览器会打开授权页。按 F12 打开开发者工具，在 `Network` 面板勾选 `Preserve log`。
4. 完成登录后，在请求列表中找到回调 URL：

`https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?...&code=...`

5. 复制 `code` 参数值，粘贴回终端的 `code:` 提示。
6. 终端会输出 `refresh_token`，复制保存。

## 在 OpenWrt 中填写

1. 打开 LuCI：`服务 -> Pixiv备份`
2. 填写 `Pixiv用户ID` 和 `Refresh Token`
3. 点击“保存并应用”

## 可选校验

```python
from pixivpy3 import AppPixivAPI

api = AppPixivAPI()
api.auth(refresh_token="你的refresh_token")
print("auth ok")
```

## 常见问题

- `ImportError: cannot import name 'EX_OK' from 'os'`：常见于 Windows + Python 3.10，改用 Python 3.11+ 或使用方案 B。
- 登录后无 token：检查网络/代理，可设置 `HTTPS_PROXY` 或 `ALL_PROXY`。
- token 失效：在 Pixiv 侧撤销授权后重新获取。

## 安全提示

- `refresh_token` 属于高敏感凭据，请勿公开或提交到仓库。
- 建议仅在可信设备上获取和存储 token。
