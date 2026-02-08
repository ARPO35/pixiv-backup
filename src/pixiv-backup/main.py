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
import random
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
DEFAULT_INTERVAL_JITTER_MS = 1000

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
            stats = self.crawler.sync_with_task_queue(user_id, download_mode, max_per_sync)
            if stats.get("rate_limited"):
                self.logger.warning("检测到限速/服务异常，结束本轮同步")
            elif stats.get("hit_max_downloads"):
                self.logger.info("本轮同步达到最大下载数量，结束本轮")
                
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
    start_parser.add_argument("--force-run", action="store_true", help="启动并立即触发下一轮扫描（等价于 start + trigger）")

    subparsers.add_parser("stop", help="停止后台服务")

    restart_parser = subparsers.add_parser("restart", help="重启后台服务")
    restart_parser.add_argument("--force-run", action="store_true", help="重启并立即触发下一轮扫描（等价于 restart + trigger）")

    subparsers.add_parser("test", help="执行服务测试（透传 init.d test）")
    subparsers.add_parser("trigger", help="跳过冷却并立即触发下一轮扫描")

    args = parser.parse_args()
    _emit_cli_audit(
        _event_line(
            "cli_command",
            command=args.command or "help",
            daemon=bool(args.daemon),
        )
    )

    if args.daemon:
        service = PixivBackupService()
        _run_daemon_loop(service)
        return EXIT_OK

    if args.command == "status":
        _print_status()
        _emit_cli_audit(_event_line("cli_command_result", command="status", status="ok"))
        return EXIT_OK

    if args.command == "log":
        ret = handle_log_command(args)
        _emit_cli_audit(_event_line("cli_command_result", command="log", status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "repair":
        ret = handle_repair_command(args)
        _emit_cli_audit(_event_line("cli_command_result", command="repair", status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "start":
        ret = _run_initd_command("start")
        if args.force_run:
            trigger_ret = _trigger_immediate_scan("cli_start_force_run")
            if ret == EXIT_OK:
                ret = trigger_ret
        _emit_cli_audit(_event_line("cli_command_result", command="start", force_run=bool(args.force_run), status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "stop":
        ret = _run_initd_command("stop")
        _emit_cli_audit(_event_line("cli_command_result", command="stop", status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "restart":
        ret = _run_initd_command("restart")
        if args.force_run:
            trigger_ret = _trigger_immediate_scan("cli_restart_force_run")
            if ret == EXIT_OK:
                ret = trigger_ret
        _emit_cli_audit(_event_line("cli_command_result", command="restart", force_run=bool(args.force_run), status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "test":
        ret = _run_initd_command("test")
        _emit_cli_audit(_event_line("cli_command_result", command="test", status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "trigger":
        ret = _trigger_immediate_scan("cli_trigger")
        _emit_cli_audit(_event_line("cli_command_result", command="trigger", status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    if args.command == "run":
        if args.count <= 0:
            print("参数错误: run 模式必须指定大于 0 的下载数量，例如: pixiv-backup run 20", file=sys.stderr)
            _emit_cli_audit(_event_line("cli_command_result", command="run", status="usage_error", exit_code=EXIT_USAGE))
            return EXIT_USAGE
        service = PixivBackupService()
        result = service.run(max_download_limit=args.count)
        ret = EXIT_OK if result.get("success") else EXIT_ERROR
        _emit_cli_audit(_event_line("cli_command_result", command="run", count=args.count, status="ok" if ret == EXIT_OK else "error", exit_code=ret))
        return ret

    parser.print_help()
    _emit_cli_audit(_event_line("cli_command_result", command="help", status="usage_error", exit_code=EXIT_USAGE))
    return EXIT_USAGE


def _run_daemon_loop(service):
    """守护进程模式：固定巡检 + 冷却策略"""
    sync_interval_minutes = service.config.get_sync_interval_minutes()
    cooldown_limit_minutes = service.config.get_cooldown_after_limit_minutes()
    cooldown_error_minutes = service.config.get_cooldown_after_error_minutes()
    interval_jitter_ms = service.config.get_interval_jitter_ms()

    while True:
        service.logger.info(_event_line("daemon_cycle_start", mode=service.config.get_download_mode(), max_downloads=service.config.get_max_downloads()))
        result = service.run(max_download_limit=service.config.get_max_downloads())
        now = datetime.now()

        if result.get("rate_limited"):
            base_wait_seconds = cooldown_error_minutes * 60
            reason = "rate_limit_or_server_error"
        elif result.get("hit_max_downloads"):
            base_wait_seconds = cooldown_limit_minutes * 60
            reason = "hit_max_downloads"
        else:
            base_wait_seconds = sync_interval_minutes * 60
            reason = "normal_interval"

        jitter_seconds = _random_non_negative_jitter_seconds(interval_jitter_ms)
        wait_seconds = base_wait_seconds + jitter_seconds
        next_run = now + timedelta(seconds=wait_seconds)
        service._write_runtime_status({
            "state": "cooldown",
            "phase": "waiting",
            "cooldown_reason": reason,
            "next_run_at": next_run.strftime("%Y-%m-%d %H:%M:%S"),
            "cooldown_seconds": wait_seconds,
            "base_cooldown_seconds": base_wait_seconds,
            "cooldown_jitter_ms": int(jitter_seconds * 1000),
        })
        service.logger.info(
            f"进入冷却({reason})，基础等待 {base_wait_seconds}s，"
            f"随机偏移 +{int(jitter_seconds * 1000)}ms，"
            f"下次巡检时间: {next_run.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        service.logger.info(
            _event_line(
                "daemon_cycle_cooldown",
                reason=reason,
                base_wait_seconds=base_wait_seconds,
                jitter_ms=int(jitter_seconds * 1000),
                wait_seconds=wait_seconds,
                next_run_at=next_run.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
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
        _emit_cli_audit(_event_line("log_command", status="usage_error", reason="invalid_lines", lines=args.lines))
        return EXIT_USAGE

    if args.file and args.syslog:
        print("参数错误: --file 和 --syslog 不能同时使用，请二选一", file=sys.stderr)
        _emit_cli_audit(_event_line("log_command", status="usage_error", reason="source_conflict"))
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
            _emit_cli_audit(_event_line("log_command", status="error", source="file", reason="file_not_found", log_dir=str(log_dir)))
            return EXIT_ERROR
        _print_tail_from_file(latest_file, args.lines)
        _emit_cli_audit(_event_line("log_command", status="ok", source="file", lines=args.lines, follow=not args.no_follow))
        if args.no_follow:
            return EXIT_OK
        return _follow_file_logs(log_dir, latest_file)

    if source == "syslog":
        if not has_syslog:
            print("系统不支持 logread，无法读取 syslog", file=sys.stderr)
            _emit_cli_audit(_event_line("log_command", status="error", source="syslog", reason="logread_not_found"))
            return EXIT_ERROR
        ret = _print_tail_from_syslog(args.lines)
        _emit_cli_audit(_event_line("log_command", status="ok" if ret == EXIT_OK else "error", source="syslog", lines=args.lines, follow=not args.no_follow))
        if ret != EXIT_OK or args.no_follow:
            return ret
        return _follow_syslog()

    # auto: 文件日志优先，缺失时回退到 syslog
    if latest_file:
        _print_tail_from_file(latest_file, args.lines)
        _emit_cli_audit(_event_line("log_command", status="ok", source="auto_file", lines=args.lines, follow=not args.no_follow))
        if args.no_follow:
            return EXIT_OK
        return _follow_file_logs(log_dir, latest_file)

    if has_syslog:
        ret = _print_tail_from_syslog(args.lines)
        _emit_cli_audit(_event_line("log_command", status="ok" if ret == EXIT_OK else "error", source="auto_syslog", lines=args.lines, follow=not args.no_follow))
        if ret != EXIT_OK or args.no_follow:
            return ret
        return _follow_syslog()

    print("无可用日志来源: 文件日志不存在且系统不支持 logread", file=sys.stderr)
    _emit_cli_audit(_event_line("log_command", status="error", source="auto", reason="no_available_source"))
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
    _emit_cli_audit(
        _event_line(
            "initd_command",
            action=action,
            status="ok" if result.returncode == 0 else "error",
            exit_code=result.returncode,
        )
    )
    return EXIT_OK if result.returncode == 0 else EXIT_ERROR


def _random_non_negative_jitter_seconds(max_jitter_ms):
    try:
        jitter_ms = int(max_jitter_ms)
    except Exception:
        jitter_ms = DEFAULT_INTERVAL_JITTER_MS
    if jitter_ms < 0:
        jitter_ms = 0
    if jitter_ms == 0:
        return 0.0
    return random.randint(0, jitter_ms) / 1000.0


def _read_uci_value(key):
    for cmd in ("/sbin/uci", "/bin/uci", "uci"):
        try:
            result = subprocess.run(
                [cmd, "-q", "get", key],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            continue
        if result.returncode == 0:
            value = (result.stdout or "").strip()
            if value:
                return value
    return None


def _resolve_force_run_output_dirs():
    candidates = []
    seen = set()

    def _add(path_like):
        if not path_like:
            return
        p = Path(str(path_like))
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        candidates.append(p)

    # 优先直接读取 UCI，避免某些环境下 ConfigManager 解析失败时写错目录
    _add(_read_uci_value("pixiv-backup.settings.output_dir"))
    _add(_read_uci_value("pixiv-backup.main.output_dir"))

    _add("/mnt/sda1/pixiv-backup")
    return candidates


def _emit_cli_audit(message):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - pixiv-backup.cli - INFO - {message}"
    for output_dir in _resolve_force_run_output_dirs():
        try:
            log_dir = Path(output_dir) / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"pixiv-backup-{datetime.now().strftime('%Y%m%d')}.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    try:
        if shutil.which("logger"):
            subprocess.run(["logger", "-t", "pixiv-backup.cli", message], check=False)
    except Exception:
        pass


def _sanitize_event_value(value):
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    return text if text else "-"


def _event_line(event, **fields):
    parts = [f"event={_sanitize_event_value(event)}"]
    for key, value in fields.items():
        parts.append(f"{_sanitize_event_value(key)}={_sanitize_event_value(value)}")
    return " ".join(parts)


def _touch_force_run_flag():
    success_paths = []
    errors = []
    output_dirs = _resolve_force_run_output_dirs()

    if not output_dirs:
        print("写入 force_run.flag 失败: 未找到可用输出目录", file=sys.stderr)
        _emit_cli_audit("event=force_run_flag status=error reason=no_output_dir")
        return False

    for output_dir in output_dirs:
        flag_file = Path(output_dir) / "data" / "force_run.flag"
        try:
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.touch()
            success_paths.append(str(flag_file))
        except Exception as e:
            errors.append(f"{flag_file}: {e}")

    if success_paths:
        for p in success_paths:
            print(f"已写入 force_run.flag: {p}")
        _emit_cli_audit(f"event=force_run_flag status=ok paths={';'.join(success_paths)}")
        return True

    print("写入 force_run.flag 失败:", file=sys.stderr)
    for err in errors:
        print(f"- {err}", file=sys.stderr)
    _emit_cli_audit(f"event=force_run_flag status=error detail={';'.join(errors)}")
    return False


def _is_service_running():
    initd = Path(INITD_PATH)
    if not initd.exists():
        return False
    result = subprocess.run([str(initd), "running"], capture_output=True, text=True, check=False)
    return result.returncode == 0


def _write_runtime_status_patch(output_dir, patch):
    status_file = Path(output_dir) / "data" / "status.json"
    current = {}
    if status_file.exists():
        try:
            with open(status_file, "r", encoding="utf-8") as f:
                current = json.load(f)
        except Exception:
            current = {}
    current.update(patch)
    current["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_file.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


def _record_trigger_status(source, status, detail):
    patch = {
        "last_trigger_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "last_trigger_source": source,
        "last_trigger_status": status,
        "last_trigger_detail": detail,
    }
    for output_dir in _resolve_force_run_output_dirs():
        try:
            _write_runtime_status_patch(output_dir, patch)
        except Exception:
            pass


def _trigger_immediate_scan(source):
    running = _is_service_running()
    ok = _touch_force_run_flag()
    if ok:
        detail = "service_running" if running else "service_not_running"
        _record_trigger_status(source, "ok", detail)
        _emit_cli_audit(_event_line("trigger_request", source=source, status="ok", service_running=running))
        if running:
            print("已触发立即扫描请求（服务运行中，等待将被中断）")
        else:
            print("已写入触发标志（服务当前未运行，启动后将生效）")
        return EXIT_OK

    _record_trigger_status(source, "error", "flag_write_failed")
    _emit_cli_audit(_event_line("trigger_request", source=source, status="error"))
    print("触发立即扫描失败：无法写入 force_run.flag", file=sys.stderr)
    return EXIT_ERROR

if __name__ == "__main__":
    sys.exit(main())
