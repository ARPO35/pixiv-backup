import os
import json
import subprocess
from pathlib import Path

class ConfigManager:
    def __init__(self, config_file="/etc/config/pixiv-backup"):
        """初始化配置管理器"""
        self.config_file = config_file
        self.config_data = {}
        self.main_section = "settings"
        self._load_config()
        self.main_section = self._detect_main_section()
        
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

    def _detect_main_section(self):
        """检测主配置节名，兼容旧版 main 和新版 settings"""
        if "settings" in self.config_data:
            return "settings"
        if "main" in self.config_data:
            return "main"
        return "settings"
            
    def get(self, section, option, default=None):
        """获取配置值"""
        if section in self.config_data and option in self.config_data[section]:
            return self.config_data[section][option]
        # 兼容主配置节重命名：main <-> settings
        if section in ("main", "settings"):
            compat_section = self.main_section
            if compat_section in self.config_data and option in self.config_data[compat_section]:
                return self.config_data[compat_section][option]
        return default
        
    def validate_required(self):
        """验证必要配置"""
        required_configs = [
            (self.main_section, "user_id"),
            (self.main_section, "refresh_token"),
            (self.main_section, "output_dir")
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
        return self.get(self.main_section, "user_id")
        
    def get_refresh_token(self):
        """获取refresh token"""
        return self.get(self.main_section, "refresh_token")
        
    def get_output_dir(self):
        """获取输出目录"""
        dir_path = self.get(self.main_section, "output_dir")
        if not dir_path:
            dir_path = "/mnt/sda1/pixiv-backup"
        return Path(str(dir_path))
        
    def get_download_mode(self):
        """获取下载模式"""
        return self.get(self.main_section, "mode", "bookmarks")
        
    def get_restrict_mode(self):
        """获取内容范围"""
        return self.get(self.main_section, "restrict", "public")
        
    def get_max_downloads(self):
        """获取最大下载数量"""
        try:
            return int(self.get(self.main_section, "max_downloads", "1000"))
        except:
            return 1000
            
    def get_timeout(self):
        """获取超时时间"""
        try:
            return int(self.get(self.main_section, "timeout", "30"))
        except:
            return 30

    def get_sync_interval_minutes(self):
        """获取巡检间隔（分钟）"""
        try:
            value = int(self.get(self.main_section, "sync_interval_minutes", "360"))
            return value if value > 0 else 360
        except:
            return 360

    def get_cooldown_after_limit_minutes(self):
        """获取达到下载上限后的冷却时间（分钟）"""
        try:
            value = int(self.get(self.main_section, "cooldown_after_limit_minutes", "60"))
            return value if value > 0 else 60
        except:
            return 60

    def get_cooldown_after_error_minutes(self):
        """获取限速/错误后的冷却时间（分钟）"""
        try:
            value = int(self.get(self.main_section, "cooldown_after_error_minutes", "180"))
            return value if value > 0 else 180
        except:
            return 180

    def get_high_speed_queue_size(self):
        """获取高速队列数量"""
        try:
            value = int(self.get(self.main_section, "high_speed_queue_size", "20"))
            return value if value >= 0 else 20
        except:
            return 20

    def get_low_speed_interval_seconds(self):
        """获取低速队列间隔时间（秒）"""
        try:
            value = float(self.get(self.main_section, "low_speed_interval_seconds", "1.5"))
            return value if value >= 0 else 1.5
        except:
            return 1.5
        
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
        """当前版本不启用内容过滤"""
        return True, "通过"
