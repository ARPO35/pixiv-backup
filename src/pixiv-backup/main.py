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
import shutil
import subprocess
from pathlib import Path
from collections import deque
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

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
LOG_PATTERN = "pixiv-backup-*.log"
INITD_PATH = "/etc/init.d/pixiv-backup"

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
        handlers = [logging.StreamHandler(sys.stdout)]
        fallback_message = None

        primary_log_dir = Path(self.config.get_output_dir()) / "data" / "logs"
        primary_log_file = primary_log_dir / f"pixiv-backup-{datetime.now().strftime('%Y%m%d')}.log"

        try:
            primary_log_dir.mkdir(parents=True, exist_ok=True)
            handlers.insert(0, logging.FileHandler(primary_log_file, encoding='utf-8'))
        except Exception as primary_error:
            # 回退到 /tmp，避免因权限问题导致服务直接崩溃
            tmp_log_dir = Path("/tmp/pixiv-backup")
            tmp_log_file = tmp_log_dir / f"pixiv-backup-{datetime.now().strftime('%Y%m%d')}.log"
            try:
                tmp_log_dir.mkdir(parents=True, exist_ok=True)
                handlers.insert(0, logging.FileHandler(tmp_log_file, encoding='utf-8'))
                fallback_message = (
                    f"主日志文件不可写({primary_log_file}: {primary_error})，"
                    f"已回退到 {tmp_log_file}"
                )
            except Exception as tmp_error:
                fallback_message = (
                    f"日志文件不可写({primary_log_file}: {primary_error}; /tmp 回退失败: {tmp_error})，"
                    "将仅输出到 stdout"
                )

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers,
            force=True,
        )

        logger = logging.getLogger(__name__)
        if fallback_message:
            logger.warning(fallback_message)
        return logger
        
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
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self.logger.info(f"创建目录: {directory}")
            except Exception as e:
                self.logger.error(f"创建目录失败: {directory} ({e})")
                raise

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
        try:
            current = self._read_runtime_status()
            current.update(patch)
            current["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status_file = self._status_file()
            status_file.parent.mkdir(parents=True, exist_ok=True)
            with open(status_file, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"写入运行状态失败: {e}")

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
    parser = argparse.ArgumentParser(
        description="Pixiv 备份服务",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=(
            "log 参数摘要:\n"
            "  pixiv-backup log [-n N] [--no-follow] [--file | --syslog]\n"
            "    -n/--lines      先输出最近 N 行（默认 100）\n"
            "    --no-follow     仅输出快照，不持续追踪\n"
            "    --file          强制读取文件日志\n"
            "    --syslog        强制读取系统日志"
        ),
    )
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="单次运行模式")
    run_parser.add_argument("count", type=int, help="run 模式单次下载数量")

    subparsers.add_parser("status", help="查看当前状态")

    log_parser = subparsers.add_parser("log", help="查看日志（默认持续追踪）")
    log_parser.add_argument("-n", "--lines", type=int, default=100, help="先输出最近 N 行日志（默认: 100）")
    log_parser.add_argument("--no-follow", action="store_true", help="仅输出快照，不持续追踪")
    log_parser.add_argument("--file", action="store_true", help="强制从文件日志读取")
    log_parser.add_argument("--syslog", action="store_true", help="强制从系统日志读取")

    repair_parser = subparsers.add_parser("repair", help="诊断并修复常见问题")
    repair_parser.add_argument("--check", action="store_true", help="仅检查，不执行修复")
    repair_parser.add_argument("--apply", action="store_true", help="直接执行修复")
    repair_parser.add_argument("-y", "--yes", action="store_true", help="自动确认修复")

    start_parser = subparsers.add_parser("start", help="启动后台服务")
    start_parser.add_argument("--force-run", action="store_true", help="启动前写入 force_run.flag 以立即触发新一轮")

    subparsers.add_parser("stop", help="停止后台服务")

    restart_parser = subparsers.add_parser("restart", help="重启后台服务")
    restart_parser.add_argument("--force-run", action="store_true", help="重启前写入 force_run.flag 以立即触发新一轮")

    subparsers.add_parser("test", help="执行服务测试（透传 init.d test）")

    args = parser.parse_args()

    if args.daemon:
        service = PixivBackupService()
        _run_daemon_loop(service)
        return EXIT_OK

    if args.command == "status":
        _print_status()
        return EXIT_OK

    if args.command == "log":
        return handle_log_command(args)

    if args.command == "repair":
        return handle_repair_command(args)

    if args.command == "start":
        if args.force_run:
            _touch_force_run_flag()
        return _run_initd_command("start")

    if args.command == "stop":
        return _run_initd_command("stop")

    if args.command == "restart":
        if args.force_run:
            _touch_force_run_flag()
        return _run_initd_command("restart")

    if args.command == "test":
        return _run_initd_command("test")

    if args.command == "run":
        if args.count <= 0:
            print("参数错误: run 模式必须指定大于 0 的下载数量，例如: pixiv-backup run 20", file=sys.stderr)
            return EXIT_USAGE
        service = PixivBackupService()
        result = service.run(max_download_limit=args.count)
        return EXIT_OK if result.get("success") else EXIT_ERROR

    parser.print_help()
    return EXIT_USAGE


def _run_daemon_loop(service):
    """守护进程模式：固定巡检 + 冷却策略"""
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


def _print_status():
    """只读状态输出"""
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


def _latest_log_file(log_dir):
    if not log_dir.exists():
        return None
    files = list(log_dir.glob(LOG_PATTERN))
    if not files:
        return None
    try:
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return files[0]


def _print_tail_from_file(log_file, lines):
    buffer = deque(maxlen=lines)
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            buffer.append(line)
    for line in buffer:
        print(line, end="")


def _follow_file_logs(log_dir, log_file):
    current_file = log_file
    stream = open(current_file, "r", encoding="utf-8", errors="replace")
    stream.seek(0, os.SEEK_END)

    try:
        while True:
            line = stream.readline()
            if line:
                print(line, end="", flush=True)
                continue

            # 检测日志轮转，自动切换到最新文件
            latest = _latest_log_file(log_dir)
            if latest and latest != current_file:
                stream.close()
                current_file = latest
                stream = open(current_file, "r", encoding="utf-8", errors="replace")
                stream.seek(0, os.SEEK_END)
                print(f"\n[log] 已切换到新日志文件: {current_file}", flush=True)
                continue

            # 检测文件被截断，回到文件开头继续追踪
            try:
                current_size = current_file.stat().st_size
            except OSError:
                current_size = 0
            if stream.tell() > current_size:
                stream.seek(0)

            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[log] 已停止日志追踪")
        return EXIT_OK
    finally:
        stream.close()


def _print_tail_from_syslog(lines):
    try:
        result = subprocess.run(
            ["logread", "-e", "pixiv-backup"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        print(f"读取系统日志失败: {e}", file=sys.stderr)
        return EXIT_ERROR

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        print(f"读取系统日志失败: {err or 'logread 返回非零状态'}", file=sys.stderr)
        return EXIT_ERROR

    output_lines = result.stdout.splitlines()
    for line in output_lines[-lines:]:
        print(line)
    return EXIT_OK


def _follow_syslog():
    try:
        proc = subprocess.Popen(["logread", "-f", "-e", "pixiv-backup"])
    except OSError as e:
        print(f"启动系统日志追踪失败: {e}", file=sys.stderr)
        return EXIT_ERROR

    try:
        proc.wait()
        return EXIT_OK if proc.returncode == 0 else EXIT_ERROR
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        print("\n[log] 已停止日志追踪")
        return EXIT_OK


def handle_log_command(args):
    if args.lines <= 0:
        print("参数错误: --lines 必须大于 0", file=sys.stderr)
        return EXIT_USAGE

    if args.file and args.syslog:
        print("参数错误: --file 和 --syslog 不能同时使用，请二选一", file=sys.stderr)
        return EXIT_USAGE

    config = ConfigManager()
    log_dir = config.get_log_dir()
    latest_file = _latest_log_file(log_dir)
    has_syslog = shutil.which("logread") is not None

    source = "auto"
    if args.file:
        source = "file"
    elif args.syslog:
        source = "syslog"

    if source == "file":
        if not latest_file:
            print(f"未找到文件日志: {log_dir}", file=sys.stderr)
            return EXIT_ERROR
        _print_tail_from_file(latest_file, args.lines)
        if args.no_follow:
            return EXIT_OK
        return _follow_file_logs(log_dir, latest_file)

    if source == "syslog":
        if not has_syslog:
            print("系统不支持 logread，无法读取 syslog", file=sys.stderr)
            return EXIT_ERROR
        ret = _print_tail_from_syslog(args.lines)
        if ret != EXIT_OK or args.no_follow:
            return ret
        return _follow_syslog()

    # auto: 文件日志优先，缺失时回退到 syslog
    if latest_file:
        _print_tail_from_file(latest_file, args.lines)
        if args.no_follow:
            return EXIT_OK
        return _follow_file_logs(log_dir, latest_file)

    if has_syslog:
        ret = _print_tail_from_syslog(args.lines)
        if ret != EXIT_OK or args.no_follow:
            return ret
        return _follow_syslog()

    print("无可用日志来源: 文件日志不存在且系统不支持 logread", file=sys.stderr)
    return EXIT_ERROR


def _is_interactive_tty():
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _confirm_repair():
    try:
        choice = input("检测到可修复问题，是否立即修复？[y/N]: ").strip().lower()
    except EOFError:
        return False
    return choice in ("y", "yes")


def _collect_repair_issues(config):
    issues = []

    # 依赖检查
    try:
        import requests  # noqa: F401
    except Exception as e:
        issues.append({
            "id": "missing_requests",
            "message": f"依赖缺失: requests ({e})",
            "fix_action": "install_requests",
            "fixable": True,
        })

    try:
        import pixivpy3  # noqa: F401
    except Exception as e:
        issues.append({
            "id": "missing_pixivpy3",
            "message": f"依赖缺失: pixivpy3 ({e})",
            "fix_action": "install_pixivpy3",
            "fixable": True,
        })

    # 配置检查
    if not config.validate_required():
        issues.append({
            "id": "invalid_required_config",
            "message": "UCI 必填配置不完整（user_id/refresh_token/output_dir）",
            "fix_action": None,
            "fixable": False,
        })

    # 目录检查
    output_dir = Path(config.get_output_dir())
    required_dirs = [
        output_dir / "img",
        output_dir / "metadata",
        output_dir / "data" / "cache",
        output_dir / "data" / "thumbnails",
        output_dir / "data" / "logs",
    ]
    for d in required_dirs:
        if not d.exists():
            issues.append({
                "id": "missing_dir",
                "message": f"目录不存在: {d}",
                "fix_action": "create_runtime_dirs",
                "fixable": True,
            })

    # 数据库检查（存在则可读，不存在则可初始化）
    db_path = Path(config.get_database_path())
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.execute("SELECT 1")
            conn.close()
        except Exception as e:
            issues.append({
                "id": "db_open_failed",
                "message": f"数据库无法打开: {db_path} ({e})",
                "fix_action": "init_database",
                "fixable": True,
            })
    else:
        issues.append({
            "id": "db_missing",
            "message": f"数据库不存在: {db_path}",
            "fix_action": "init_database",
            "fixable": True,
        })

    return issues


def _install_with_pip(package_name):
    pip3 = shutil.which("pip3")
    if not pip3:
        return False, "pip3 不可用"
    result = subprocess.run(
        [pip3, "install", "--no-cache-dir", package_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return False, message or "安装失败"
    return True, f"已安装 {package_name}"


def _apply_repair_action(config, action):
    if action == "install_pixivpy3":
        ok, message = _install_with_pip("pixivpy3")
        return ok, f"pixivpy3: {message}"
    if action == "install_requests":
        ok, message = _install_with_pip("requests")
        return ok, f"requests: {message}"
    if action == "create_runtime_dirs":
        output_dir = Path(config.get_output_dir())
        for d in [
            output_dir / "img",
            output_dir / "metadata",
            output_dir / "data" / "cache",
            output_dir / "data" / "thumbnails",
            output_dir / "data" / "logs",
        ]:
            d.mkdir(parents=True, exist_ok=True)
        return True, "已补齐运行目录"
    if action == "init_database":
        DatabaseManager(config)
        return True, "已初始化/迁移数据库结构"
    return False, f"未知修复动作: {action}"


def _dedup_fix_actions(issues):
    actions = []
    for issue in issues:
        action = issue.get("fix_action")
        if action and action not in actions:
            actions.append(action)
    return actions


def handle_repair_command(args):
    if args.check and args.apply:
        print("参数错误: --check 和 --apply 不能同时使用", file=sys.stderr)
        return EXIT_USAGE

    config = ConfigManager()
    issues = _collect_repair_issues(config)

    if not issues:
        print("检查完成：未发现问题。")
        return EXIT_OK

    print(f"检查完成：发现 {len(issues)} 项问题：")
    for idx, issue in enumerate(issues, start=1):
        status = "可修复" if issue.get("fixable") else "需手动处理"
        print(f"{idx}. [{status}] {issue.get('message')}")

    if args.check:
        return EXIT_USAGE

    apply_fix = args.apply
    if not apply_fix:
        if args.yes:
            apply_fix = True
        elif _is_interactive_tty():
            apply_fix = _confirm_repair()
        else:
            # 按既定计划：非交互场景默认自动修复
            print("检测到非交互环境，默认执行修复。")
            apply_fix = True

    if not apply_fix:
        print("未执行修复。")
        return EXIT_USAGE

    actions = _dedup_fix_actions(issues)
    if not actions:
        print("未发现可自动修复的问题，请按提示手动处理。", file=sys.stderr)
        return EXIT_ERROR

    print("开始执行修复...")
    for action in actions:
        ok, message = _apply_repair_action(config, action)
        flag = "成功" if ok else "失败"
        print(f"- {flag}: {message}")
        if not ok:
            return EXIT_ERROR

    remaining = _collect_repair_issues(config)
    if remaining:
        print(f"修复后仍有 {len(remaining)} 项问题：", file=sys.stderr)
        for idx, issue in enumerate(remaining, start=1):
            status = "可修复" if issue.get("fixable") else "需手动处理"
            print(f"{idx}. [{status}] {issue.get('message')}", file=sys.stderr)
        return EXIT_ERROR

    print("修复完成：问题已清除。")
    return EXIT_OK


def _run_initd_command(action):
    initd = Path(INITD_PATH)
    if not initd.exists():
        print(f"服务脚本不存在: {initd}", file=sys.stderr)
        return EXIT_ERROR

    result = subprocess.run(
        [str(initd), action],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return EXIT_OK if result.returncode == 0 else EXIT_ERROR


def _touch_force_run_flag():
    try:
        config = ConfigManager()
        flag_file = Path(config.get_output_dir()) / "data" / "force_run.flag"
        flag_file.parent.mkdir(parents=True, exist_ok=True)
        flag_file.touch()
    except Exception as e:
        print(f"写入 force_run.flag 失败: {e}", file=sys.stderr)

if __name__ == "__main__":
    sys.exit(main())
