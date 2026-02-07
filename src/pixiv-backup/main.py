#!/usr/bin/env python3
"""
Pixiv备份服务主程序
"""

import os
import sys
import json
import time
import logging
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime

# 添加模块搜索路径
# 支持直接运行和安装后运行
_possible_paths = [
    os.path.dirname(os.path.abspath(__file__)),  # 直接运行
    "/usr/share/pixiv-backup",                    # 安装后
]
for path in _possible_paths:
    if path not in sys.path:
        sys.path.insert(0, path)

from modules.config_manager import ConfigManager
from modules.auth_manager import AuthManager
from modules.crawler import PixivCrawler
from modules.database import DatabaseManager
from modules.downloader import DownloadManager

class PixivBackupService:
    def __init__(self):
        """初始化备份服务"""
        self.config = ConfigManager()
        self.logger = self._setup_logging()
        
        # 验证必要配置
        if not self.config.validate_required():
            self.logger.error("缺少必要配置，请检查设置")
            sys.exit(1)
            
        # 初始化组件
        self.auth_manager = AuthManager(self.config)
        self.database = DatabaseManager(self.config)
        self.downloader = DownloadManager(self.config)
        self.crawler = PixivCrawler(self.config, self.auth_manager, self.database, self.downloader)
        
        # 创建目录结构
        self._create_directories()
        
    def _setup_logging(self):
        """设置日志系统"""
        log_dir = Path(self.config.get_output_dir()) / "data" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f"pixiv-backup-{datetime.now().strftime('%Y%m%d')}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler(sys.stdout)
            ]
        )
        
        return logging.getLogger(__name__)
        
    def _create_directories(self):
        """创建必要的目录结构"""
        output_dir = Path(self.config.get_output_dir())
        
        directories = [
            output_dir / "img",
            output_dir / "metadata",
            output_dir / "data" / "cache",
            output_dir / "data" / "thumbnails",
            output_dir / "data" / "logs",
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"创建目录: {directory}")
            
    def run(self):
        """运行备份服务"""
        self.logger.info("开始Pixiv备份服务")
        
        try:
            # 记录开始时间
            start_time = time.time()
            
            # 连接到Pixiv API
            self.logger.info("连接到Pixiv API...")
            api_client = self.auth_manager.get_api_client()
            if not api_client:
                self.logger.error("无法连接到Pixiv API")
                return False
                
            # 根据配置运行不同的下载模式
            download_mode = self.config.get_download_mode()
            user_id = self.config.get_user_id()
            
            stats = {}
            
            if download_mode in ["bookmarks", "both"]:
                self.logger.info(f"开始下载用户 {user_id} 的收藏...")
                bookmark_stats = self.crawler.download_user_bookmarks(user_id)
                stats.update(bookmark_stats)
                
            if download_mode in ["following", "both"]:
                self.logger.info(f"开始下载用户 {user_id} 的关注用户作品...")
                following_stats = self.crawler.download_following_illusts(user_id)
                stats.update(following_stats)
                
            # 计算运行时间
            elapsed_time = time.time() - start_time
            hours, remainder = divmod(elapsed_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            # 输出统计信息
            self.logger.info("=" * 50)
            self.logger.info("备份完成!")
            self.logger.info(f"运行时间: {int(hours)}小时 {int(minutes)}分钟 {int(seconds)}秒")
            self.logger.info(f"成功下载: {stats.get('success', 0)} 个作品")
            self.logger.info(f"跳过已存在: {stats.get('skipped', 0)} 个作品")
            self.logger.info(f"失败: {stats.get('failed', 0)} 个作品")
            self.logger.info(f"总计处理: {stats.get('total', 0)} 个作品")
            self.logger.info("=" * 50)
            
            # 保存运行记录
            self._save_run_record(stats, elapsed_time)
            
            return True
            
        except KeyboardInterrupt:
            self.logger.info("用户中断操作")
            return False
        except Exception as e:
            self.logger.error(f"备份过程中发生错误: {str(e)}", exc_info=True)
            return False
            
    def _save_run_record(self, stats, elapsed_time):
        """保存运行记录"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "stats": stats,
            "elapsed_time": elapsed_time,
            "config": {
                "user_id": self.config.get_user_id(),
                "download_mode": self.config.get_download_mode(),
                "restrict": self.config.get_restrict_mode(),
                "max_downloads": self.config.get_max_downloads()
            }
        }
        
        record_file = Path(self.config.get_output_dir()) / "data" / "run_history.json"
        
        # 读取历史记录
        history = []
        if record_file.exists():
            try:
                with open(record_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except:
                history = []
                
        # 添加新记录（最多保存最近100次）
        history.append(record)
        if len(history) > 100:
            history = history[-100:]
            
        # 保存记录
        with open(record_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
            
        # 更新最后运行时间
        last_run_file = Path(self.config.get_output_dir()) / "data" / "last_run.txt"
        with open(last_run_file, 'w', encoding='utf-8') as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="Pixiv 备份服务")
    parser.add_argument("command", nargs="?", choices=["run", "status"], default="run")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    args = parser.parse_args()

    if args.command == "status":
        config = ConfigManager()
        db_path = config.get_database_path()
        print("Pixiv Backup 状态")
        print(f"配置节: {config.main_section}")
        print(f"用户ID: {config.get_user_id() or '未设置'}")
        print(f"输出目录: {config.get_output_dir()}")
        print(f"下载模式: {config.get_download_mode()}")
        print(f"定时任务: {'启用' if config.is_schedule_enabled() else '禁用'}")
        print(f"配置完整: {'是' if config.validate_required() else '否'}")
        print(f"数据库: {db_path} ({'存在' if Path(db_path).exists() else '不存在'})")
        return

    service = PixivBackupService()

    if args.daemon:
        # 守护进程模式
        while True:
            service.run()
            # 检查是否需要定时运行
            if not service.config.is_schedule_enabled():
                break

            # 计算下一次运行时间
            next_run = service.config.get_next_schedule_time()
            if next_run:
                wait_seconds = (next_run - datetime.now()).total_seconds()
                if wait_seconds > 0:
                    service.logger.info(f"等待下次运行: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
                    time.sleep(wait_seconds)
            else:
                # 没有定时任务，退出
                break
    else:
        # 单次运行模式
        success = service.run()
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
