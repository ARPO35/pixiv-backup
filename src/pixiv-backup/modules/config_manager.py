import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, time as dt_time, timedelta

class ConfigManager:
    def __init__(self, config_file="/etc/config/pixiv-backup"):
        """初始化配置管理器"""
        self.config_file = config_file
        self.config_data = {}
        self._load_config()
        
    def _load_config(self):
        """加载UCI配置"""
        try:
            # 使用uci命令读取配置
            result = subprocess.run(
                ["uci", "-q", "show", "pixiv-backup"],
                capture_output=True,
                text=True,
                check=True
            )
            
            # 解析uci输出
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                    
                # 解析格式: pixiv-backup.main.enabled='1'
                parts = line.split('=', 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    value = parts[1].strip().strip("'")
                    
                    # 解析section和option
                    # 格式: pixiv-backup.节名.配置项
                    config_parts = key.split('.')
                    if len(config_parts) == 3:
                        section = config_parts[1]
                        option = config_parts[2]
                        
                        if section not in self.config_data:
                            self.config_data[section] = {}
                            
                        self.config_data[section][option] = value
                        
        except subprocess.CalledProcessError as e:
            print(f"无法读取配置: {e}")
        except Exception as e:
            print(f"配置解析错误: {e}")
            
    def get(self, section, option, default=None):
        """获取配置值"""
        if section in self.config_data and option in self.config_data[section]:
            return self.config_data[section][option]
        return default
        
    def validate_required(self):
        """验证必要配置"""
        required_configs = [
            ("main", "user_id"),
            ("main", "refresh_token"),
            ("main", "output_dir")
        ]
        
        missing = []
        for section, option in required_configs:
            value = self.get(section, option)
            if not value or value.strip() == "":
                missing.append(f"{section}.{option}")
                
        if missing:
            print(f"缺少必要配置: {', '.join(missing)}")
            return False
            
        return True
        
    def get_user_id(self):
        """获取用户ID"""
        return self.get("main", "user_id")
        
    def get_refresh_token(self):
        """获取refresh token"""
        return self.get("main", "refresh_token")
        
    def get_output_dir(self):
        """获取输出目录"""
        dir_path = self.get("main", "output_dir")
        if not dir_path:
            dir_path = "/mnt/sda1/pixiv-backup"
        return Path(str(dir_path))
        
    def get_download_mode(self):
        """获取下载模式"""
        return self.get("main", "mode", "bookmarks")
        
    def get_restrict_mode(self):
        """获取内容范围"""
        return self.get("main", "restrict", "public")
        
    def get_max_downloads(self):
        """获取最大下载数量"""
        try:
            return int(self.get("main", "max_downloads", "1000"))
        except:
            return 1000
            
    def get_r18_mode(self):
        """获取R18处理模式"""
        return self.get("main", "r18_mode", "skip")
        
    def get_min_bookmarks(self):
        """获取最小收藏数"""
        try:
            return int(self.get("main", "min_bookmarks", "0"))
        except:
            return 0
            
    def get_include_tags(self):
        """获取包含标签"""
        tags_str = self.get("main", "include_tags", "")
        if tags_str:
            return [tag.strip() for tag in tags_str.split(',')]
        return []
        
    def get_exclude_tags(self):
        """获取排除标签"""
        tags_str = self.get("main", "exclude_tags", "")
        if tags_str:
            return [tag.strip() for tag in tags_str.split(',')]
        return []
        
    def is_proxy_enabled(self):
        """是否启用代理"""
        return self.get("main", "proxy_enabled", "0") == "1"
        
    def get_proxy_url(self):
        """获取代理URL"""
        return self.get("main", "proxy_url")
        
    def get_timeout(self):
        """获取超时时间"""
        try:
            return int(self.get("main", "timeout", "30"))
        except:
            return 30
            
    def is_schedule_enabled(self):
        """是否启用定时任务"""
        return self.get("main", "schedule_enabled", "0") == "1"
        
    def get_schedule_time(self):
        """获取定时任务时间"""
        return self.get("main", "schedule_time", "03:00")
        
    def get_next_schedule_time(self):
        """计算下一次运行时间"""
        if not self.is_schedule_enabled():
            return None
            
        schedule_time_str = self.get_schedule_time()
        try:
            # 解析时间字符串 "HH:MM"
            hour, minute = map(int, schedule_time_str.split(':'))
            schedule_time = dt_time(hour, minute)
            
            now = datetime.now()
            next_run = datetime.combine(now.date(), schedule_time)
            
            # 如果今天的时间已经过了，安排到明天
            if next_run < now:
                next_run = datetime.combine(
                    now.date() + timedelta(days=1),
                    schedule_time
                )
                
            return next_run
            
        except Exception as e:
            print(f"解析定时时间错误: {e}")
            return None
            
    def get_image_dir(self):
        """获取图片目录"""
        return self.get_output_dir() / "img"
        
    def get_metadata_dir(self):
        """获取元数据目录"""
        return self.get_output_dir() / "metadata"
        
    def get_data_dir(self):
        """获取数据目录"""
        return self.get_output_dir() / "data"
        
    def get_database_path(self):
        """获取数据库路径"""
        return self.get_data_dir() / "pixiv.db"
        
    def get_cache_dir(self):
        """获取缓存目录"""
        return self.get_data_dir() / "cache"
        
    def get_log_dir(self):
        """获取日志目录"""
        return self.get_data_dir() / "logs"
        
    def should_download_illust(self, illust_info):
        """判断是否应该下载作品"""
        # 检查R18模式
        r18_mode = self.get_r18_mode()
        x_restrict = illust_info.get("x_restrict", 0)
        
        if r18_mode == "skip" and x_restrict > 0:
            return False, "跳过R18内容"
        elif r18_mode == "only" and x_restrict == 0:
            return False, "只下载R18内容"
            
        # 检查最小收藏数
        min_bookmarks = self.get_min_bookmarks()
        bookmark_count = illust_info.get("bookmark_count", 0)
        if min_bookmarks > 0 and bookmark_count < min_bookmarks:
            return False, f"收藏数不足 {min_bookmarks}（当前: {bookmark_count}）"
            
        # 检查标签过滤
        tags = illust_info.get("tags", [])
        
        include_tags = self.get_include_tags()
        if include_tags:
            has_include_tag = any(tag in include_tags for tag in tags)
            if not has_include_tag:
                return False, f"不包含指定标签: {include_tags}"
                
        exclude_tags = self.get_exclude_tags()
        if exclude_tags:
            has_exclude_tag = any(tag in exclude_tags for tag in tags)
            if has_exclude_tag:
                return False, f"包含排除标签: {exclude_tags}"
                
        return True, "通过过滤"