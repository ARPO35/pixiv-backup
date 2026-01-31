#!/usr/bin/env python3
"""
Pixiv Token获取助手
"""

import os
import sys
import json
import webbrowser
import http.server
import socketserver
import urllib.parse
from pathlib import Path

def print_help():
    """打印帮助信息"""
    print("""
Pixiv Token获取助手
==================

使用说明:

1. 使用 get-pixivpy-token 工具（推荐）
   ----------------------------------
   pip install get-pixivpy-token
   gppt
   
   按照提示登录，工具会显示refresh_token

2. 手动获取方法
   -----------
   a. 在浏览器中登录 https://www.pixiv.net/
   b. 按F12打开开发者工具
   c. 切换到Network（网络）标签
   d. 刷新页面
   e. 查找包含 "access_token" 的请求
   f. 在请求参数或响应中找到refresh_token

3. 浏览器插件方法
   -------------
   a. 安装浏览器插件 "Pixiv Token Getter"
   b. 登录Pixiv后，插件会显示token

配置步骤:
1. 获取refresh_token
2. 在LuCI界面中配置:
   - 用户ID: 你的Pixiv用户ID
   - Refresh Token: 获取到的refresh_token
   - 输出目录: 保存图片的目录（默认 /mnt/sda1/pixiv-backup）

常见问题:
1. token无效: 确保复制的是完整的refresh_token
2. 连接失败: 检查网络连接，可能需要代理
3. 权限不足: 确保token有访问收藏和关注列表的权限

注意: refresh_token长期有效，不要泄露给他人！
""")

def get_token_interactive():
    """交互式获取token"""
    print("交互式token获取")
    print("=" * 40)
    
    print("请选择获取方式:")
    print("1. 使用get-pixivpy-token工具")
    print("2. 手动输入")
    print("3. 查看帮助")
    print("4. 退出")
    
    choice = input("请选择 (1-4): ").strip()
    
    if choice == "1":
        try:
            # 尝试导入gppt
            import subprocess
            
            print("正在运行 get-pixivpy-token...")
            result = subprocess.run(["gppt"], capture_output=True, text=True)
            
            if result.returncode == 0:
                print("获取成功!")
                print("输出:")
                print(result.stdout)
            else:
                print("运行失败:")
                print(result.stderr)
                print("\n请尝试手动安装:")
                print("pip install get-pixivpy-token")
                
        except ImportError:
            print("需要安装get-pixivpy-token:")
            print("pip install get-pixivpy-token")
            
    elif choice == "2":
        print("请输入你的Pixiv信息:")
        
        user_id = input("用户ID: ").strip()
        refresh_token = input("Refresh Token: ").strip()
        
        if user_id and refresh_token:
            # 保存配置
            config_dir = Path.home() / ".config" / "pixiv-backup"
            config_dir.mkdir(parents=True, exist_ok=True)
            
            config_file = config_dir / "config.json"
            config = {
                "user_id": user_id,
                "refresh_token": refresh_token,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
                
            print(f"配置已保存到: {config_file}")
            print("可以在LuCI界面中使用这些信息")
            
        else:
            print("信息不完整!")
            
    elif choice == "3":
        print_help()
        
    elif choice == "4":
        print("退出")
        
    else:
        print("无效选择")
        
def test_token(refresh_token):
    """测试token有效性"""
    try:
        from pixivpy3 import AppPixivAPI
        
        api = AppPixivAPI()
        api.auth(refresh_token=refresh_token)
        
        # 测试获取用户信息
        user_info = api.user_detail(660788)  # 测试用用户ID
        
        if user_info and "user" in user_info:
            print("Token测试成功!")
            print(f"API连接正常")
            return True
        else:
            print("Token测试失败: 无法获取用户信息")
            return False
            
    except Exception as e:
        print(f"Token测试失败: {e}")
        return False
        
def create_quick_config():
    """创建快速配置"""
    import time
    
    config_dir = Path("/etc/config")
    config_file = config_dir / "pixiv-backup"
    
    if config_file.exists():
        print(f"配置文件已存在: {config_file}")
        print("当前内容:")
        with open(config_file, 'r', encoding='utf-8') as f:
            print(f.read())
            
        overwrite = input("是否覆盖? (y/N): ").strip().lower()
        if overwrite != 'y':
            return
            
    print("创建配置文件...")
    
    config_content = """config main 'settings'
    option enabled '0'
    option user_id ''
    option refresh_token ''
    option output_dir '/mnt/sda1/pixiv-backup'

config download 'settings'
    option mode 'bookmarks'
    option restrict 'public'
    option max_downloads '1000'

config filter 'settings'
    option min_bookmarks '0'
    option r18_mode 'skip'
    option include_tags ''
    option exclude_tags ''

config schedule 'settings'
    option enabled '0'
    option time '03:00'

config network 'settings'
    option proxy_enabled '0'
    option proxy_url ''
    option timeout '30'
"""
    
    with open(config_file, 'w', encoding='utf-8') as f:
        f.write(config_content)
        
    print(f"配置文件已创建: {config_file}")
    print("请在LuCI界面中填写用户ID和refresh_token")
    
def main():
    """主函数"""
    import time
    
    print("Pixiv备份配置助手")
    print("=" * 50)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--help" or sys.argv[1] == "-h":
            print_help()
        elif sys.argv[1] == "--test":
            if len(sys.argv) > 2:
                test_token(sys.argv[2])
            else:
                print("用法: token_helper.py --test <refresh_token>")
        elif sys.argv[1] == "--config":
            create_quick_config()
        else:
            print_help()
    else:
        get_token_interactive()

if __name__ == "__main__":
    main()