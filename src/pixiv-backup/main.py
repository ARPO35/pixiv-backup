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
from datetime import datetime, timedelta

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
        self.crawler = PixivCrawler(self.config, self.auth_manager, self.database, self.downloader, self._on_progress)
        
        # 创建目录结构
        self._create_directories()
        self._write_runtime_status({
            "state": "idle",
            "phase": "init",
            "message": "服务已初始化",
            "processed_total": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0
        })
        
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

    def _status_file(self):
        return Path(self.config.get_output_dir()) / "data" / "status.json"

    def _force_flag_file(self):
        return Path(self.config.get_output_dir()) / "data" / "force_run.flag"

    def _read_runtime_status(self):
        status_file = self._status_file()
        if not status_file.exists():
            return {}
        try:
            with open(status_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_runtime_status(self, patch):
        current = self._read_runtime_status()
        current.update(patch)
        current["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_file = self._status_file()
        status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(current, f, ensure_ascii=False, indent=2)

    def _on_progress(self, payload):
        self._write_runtime_status(payload)

    def _consume_force_run_flag(self):
        flag = self._force_flag_file()
        if flag.exists():
            try:
                flag.unlink()
            except Exception:
                pass
            return True
        return False

    def wait_with_force_run(self, wait_seconds):
        """等待冷却/间隔，并支持被 force_run.flag 中断"""
        remaining = int(wait_seconds)
        while remaining > 0:
            if self._consume_force_run_flag():
                self.logger.info("检测到立即备份请求，跳过当前等待")
                self._write_runtime_status({
                    "state": "idle",
                    "phase": "force_triggered",
                    "message": "收到立即备份请求，开始新一轮同步"
                })
                return True
            step = 1 if remaining > 1 else remaining
            time.sleep(step)
            remaining -= step
        return False

    def _merge_stats(self, base, part):
        for key in ("success", "failed", "skipped", "total"):
            base[key] = base.get(key, 0) + int(part.get(key, 0) or 0)
        base["hit_max_downloads"] = base.get("hit_max_downloads", False) or bool(part.get("hit_max_downloads", False))
        base["rate_limited"] = base.get("rate_limited", False) or bool(part.get("rate_limited", False))
        if part.get("last_error"):
            base["last_error"] = part.get("last_error")
        return base
            
    def run(self, max_download_limit=None):
        """运行备份服务"""
        self.logger.info("开始Pixiv备份服务")
        self._write_runtime_status({
            "state": "syncing",
            "phase": "start",
            "message": "开始同步",
            "processed_total": 0,
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "hit_max_downloads": False,
            "rate_limited": False
        })
        
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
            max_per_sync = self.config.get_max_downloads() if max_download_limit is None else int(max_download_limit)
            remaining_downloads = max_per_sync if max_per_sync > 0 else 0
            
            stats = {
                "success": 0,
                "failed": 0,
                "skipped": 0,
                "total": 0,
                "hit_max_downloads": False,
                "rate_limited": False,
                "last_error": None
            }
            
            if download_mode in ["bookmarks", "both"]:
                self.logger.info(f"开始下载用户 {user_id} 的收藏...")
                bookmark_stats = self.crawler.download_user_bookmarks(user_id, remaining_downloads if max_per_sync > 0 else 0)
                self._merge_stats(stats, bookmark_stats)
                if max_per_sync > 0:
                    remaining_downloads = max(0, remaining_downloads - int(bookmark_stats.get("success", 0)))
                if stats.get("rate_limited"):
                    self.logger.warning("检测到限速/服务异常，结束本轮同步")
                elif max_per_sync > 0 and remaining_downloads <= 0:
                    stats["hit_max_downloads"] = True
                    self.logger.info("本轮同步达到最大下载数量，结束本轮")
                
            if download_mode in ["following", "both"] and not stats.get("rate_limited") and not (max_per_sync > 0 and remaining_downloads <= 0):
                self.logger.info(f"开始下载用户 {user_id} 的关注用户作品...")
                following_stats = self.crawler.download_following_illusts(user_id, remaining_downloads if max_per_sync > 0 else 0)
                self._merge_stats(stats, following_stats)
                if max_per_sync > 0:
                    remaining_downloads = max(0, remaining_downloads - int(following_stats.get("success", 0)))
                    if remaining_downloads <= 0:
                        stats["hit_max_downloads"] = True
                
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
            self._write_runtime_status({
                "state": "idle",
                "phase": "done",
                "message": "同步完成",
                "processed_total": stats.get("total", 0),
                "success": stats.get("success", 0),
                "skipped": stats.get("skipped", 0),
                "failed": stats.get("failed", 0),
                "hit_max_downloads": stats.get("hit_max_downloads", False),
                "rate_limited": stats.get("rate_limited", False),
                "last_error": stats.get("last_error"),
                "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # 保存运行记录
            self._save_run_record(stats, elapsed_time)
            
            return {
                "success": True,
                "stats": stats,
                "hit_max_downloads": stats.get("hit_max_downloads", False),
                "rate_limited": stats.get("rate_limited", False),
                "last_error": stats.get("last_error")
            }
            
        except KeyboardInterrupt:
            self.logger.info("用户中断操作")
            self._write_runtime_status({"state": "idle", "phase": "interrupted", "message": "用户中断"})
            return {"success": False, "stats": {}, "hit_max_downloads": False, "rate_limited": False, "last_error": "用户中断"}
        except Exception as e:
            self.logger.error(f"备份过程中发生错误: {str(e)}", exc_info=True)
            self._write_runtime_status({
                "state": "idle",
                "phase": "error",
                "message": "同步失败",
                "last_error": str(e)
            })
            return {"success": False, "stats": {}, "hit_max_downloads": False, "rate_limited": False, "last_error": str(e)}
            
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
    parser.add_argument("count", nargs="?", type=int, help="run 模式单次下载数量")
    parser.add_argument("--daemon", action="store_true", help="守护进程模式")
    args = parser.parse_args()

    if args.command == "status":
        config = ConfigManager()
        db_path = config.get_database_path()
        status_file = Path(config.get_output_dir()) / "data" / "status.json"
        runtime = {}
        if status_file.exists():
            try:
                runtime = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                runtime = {}
        print("Pixiv Backup 状态")
        print(f"配置节: {config.main_section}")
        print(f"用户ID: {config.get_user_id() or '未设置'}")
        print(f"输出目录: {config.get_output_dir()}")
        print(f"下载模式: {config.get_download_mode()}")
        print(f"配置完整: {'是' if config.validate_required() else '否'}")
        print(f"数据库: {db_path} ({'存在' if Path(db_path).exists() else '不存在'})")
        if runtime:
            print(f"当前状态: {runtime.get('state', 'unknown')}")
            print(f"当前阶段: {runtime.get('phase', 'unknown')}")
            print(f"已处理: {runtime.get('processed_total', 0)}")
            if runtime.get("last_error"):
                print(f"最近错误: {runtime.get('last_error')}")
        return

    service = PixivBackupService()

    if args.daemon:
        # 守护进程模式：固定巡检 + 冷却策略
        sync_interval_minutes = service.config.get_sync_interval_minutes()
        cooldown_limit_minutes = service.config.get_cooldown_after_limit_minutes()
        cooldown_error_minutes = service.config.get_cooldown_after_error_minutes()

        while True:
            result = service.run(max_download_limit=service.config.get_max_downloads())
            now = datetime.now()

            if result.get("rate_limited"):
                wait_seconds = cooldown_error_minutes * 60
                reason = "rate_limit_or_server_error"
            elif result.get("hit_max_downloads"):
                wait_seconds = cooldown_limit_minutes * 60
                reason = "hit_max_downloads"
            else:
                wait_seconds = sync_interval_minutes * 60
                reason = "normal_interval"

            next_run = now + timedelta(seconds=wait_seconds)
            service._write_runtime_status({
                "state": "cooldown",
                "phase": "waiting",
                "cooldown_reason": reason,
                "next_run_at": next_run.strftime("%Y-%m-%d %H:%M:%S"),
                "cooldown_seconds": wait_seconds,
            })
            service.logger.info(f"进入冷却({reason})，下次巡检时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
            service.wait_with_force_run(wait_seconds)
    else:
        # 单次运行模式
        if args.count is None or args.count <= 0:
            parser.error("run 模式必须指定单次下载数量，例如: pixiv-backup run 20")
        result = service.run(max_download_limit=args.count)
        sys.exit(0 if result.get("success") else 1)

if __name__ == "__main__":
    main()
