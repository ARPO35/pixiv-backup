import os
import json
import time
import hashlib
import base64
import secrets
from pathlib import Path

# 尝试导入pixivpy，如果失败则尝试安装
try:
    from pixivpy3 import AppPixivAPI
    PIXIVPY_AVAILABLE = True
except ImportError:
    PIXIVPY_AVAILABLE = False

class AuthManager:
    def __init__(self, config):
        """初始化认证管理器"""
        self.config = config
        self.api_client = None
        self.token_data = None
        
        # Pixiv API配置
        self.CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
        self.CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
        
        # 检查pixivpy是否可用
        if not PIXIVPY_AVAILABLE:
            raise ImportError("pixivpy3库未安装，请运行: pip install pixivpy3")
            
    def get_api_client(self):
        """获取API客户端"""
        if self.api_client:
            return self.api_client
            
        # 创建API客户端
        self.api_client = AppPixivAPI()
        
        # 配置代理（如果启用）
        if self.config.is_proxy_enabled():
            proxy_url = self.config.get_proxy_url()
            if proxy_url:
                self.api_client.set_proxy(proxy_url)
                
        # 设置超时
        timeout = self.config.get_timeout()
        self.api_client.timeout = timeout
        
        # 使用refresh_token登录
        refresh_token = self.config.get_refresh_token()
        if not refresh_token:
            raise ValueError("未配置refresh_token")
            
        try:
            # 尝试登录
            self.api_client.auth(refresh_token=refresh_token)
            
            # 保存token信息
            self._save_token_info()
            
            return self.api_client
            
        except Exception as e:
            print(f"认证失败: {e}")
            
            # 尝试使用保存的token
            if self._load_saved_token():
                try:
                    self.api_client.auth(access_token=self.token_data["access_token"])
                    return self.api_client
                except:
                    pass
                    
            raise Exception(f"无法连接到Pixiv API: {e}")
            
    def _save_token_info(self):
        """保存token信息"""
        if not self.api_client:
            return
            
        token_file = self.config.get_data_dir() / "token.json"
        token_data = {
            "access_token": getattr(self.api_client, "access_token", ""),
            "refresh_token": self.config.get_refresh_token(),
            "expires_at": time.time() + 3600,  # 假设1小时后过期
            "saved_at": time.time()
        }
        
        try:
            with open(token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存token失败: {e}")
            
    def _load_saved_token(self):
        """加载保存的token"""
        token_file = self.config.get_data_dir() / "token.json"
        
        if not token_file.exists():
            return False
            
        try:
            with open(token_file, 'r', encoding='utf-8') as f:
                self.token_data = json.load(f)
                
            # 检查token是否过期
            expires_at = self.token_data.get("expires_at", 0)
            if time.time() < expires_at:
                return True
                
        except Exception as e:
            print(f"加载token失败: {e}")
            
        return False
        
    def refresh_token_if_needed(self):
        """如果需要则刷新token"""
        if not self.token_data:
            return False
            
        expires_at = self.token_data.get("expires_at", 0)
        
        # 如果token即将过期（5分钟内），刷新它
        if time.time() > (expires_at - 300):
            try:
                refresh_token = self.token_data.get("refresh_token")
                if refresh_token:
                    self.api_client.auth(refresh_token=refresh_token)
                    self._save_token_info()
                    return True
            except Exception as e:
                print(f"刷新token失败: {e}")
                
        return False
        
    def test_connection(self):
        """测试连接"""
        try:
            client = self.get_api_client()
            
            # 测试获取用户信息
            user_id = self.config.get_user_id()
            if user_id:
                user_info = client.user_detail(int(user_id))
                if user_info and "user" in user_info:
                    return {
                        "success": True,
                        "user_name": user_info["user"]["name"],
                        "account": user_info["user"]["account"],
                        "is_premium": user_info["user"]["is_premium"]
                    }
                    
            return {"success": True, "message": "连接成功"}
            
        except Exception as e:
            return {"success": False, "error": str(e)}
            
    def get_token_help_info(self):
        """获取token帮助信息"""
        help_info = """
        # 如何获取Pixiv Refresh Token
        
        ## 方法一：使用get-pixivpy-token工具（推荐）
        
        1. 安装工具：
           ```bash
           pip install get-pixivpy-token
           ```
           
        2. 运行工具获取token：
           ```bash
           gppt
           ```
           
        3. 按照提示登录Pixiv账号
        4. 工具会显示refresh_token，复制它
        
        ## 方法二：手动获取（复杂）
        
        1. 在浏览器中登录Pixiv
        2. 打开开发者工具（F12）
        3. 访问：https://www.pixiv.net/
        4. 在Network标签中查找包含"access_token"的请求
        5. 提取refresh_token参数
        
        ## 方法三：使用浏览器插件
        
        1. 安装"Pixiv Token Getter"等浏览器插件
        2. 登录Pixiv后，插件会自动显示token
        
        ## 重要提示
        
        - refresh_token长期有效（除非手动撤销）
        - 不要泄露你的token
        - token绑定到你的Pixiv账号
        """
        
        return help_info