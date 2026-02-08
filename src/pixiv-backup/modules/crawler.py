import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict


class PixivCrawler:
    def __init__(self, config, auth_manager, database, downloader, progress_callback=None):
        """初始化爬虫"""
        self.config = config
        self.auth_manager = auth_manager
        self.database = database
        self.downloader = downloader
        self.progress_callback = progress_callback
        self.api = None
        self.logger = logging.getLogger(__name__)
        self.high_speed_queue_size = self.config.get_high_speed_queue_size()
        self.low_speed_interval_seconds = self.config.get_low_speed_interval_seconds()
        self.task_queue_file = self.config.get_data_dir() / "task_queue.json"
        self._log_event(
            "crawler_init",
            high_speed_queue_size=self.high_speed_queue_size,
            low_speed_interval_seconds=self.low_speed_interval_seconds,
            task_queue_file=self.task_queue_file,
        )

    def _event_line(self, event, **fields):
        parts = [f"event={self._normalize_event_value(event)}"]
        for key, value in fields.items():
            parts.append(f"{self._normalize_event_value(key)}={self._normalize_event_value(value)}")
        return " ".join(parts)

    def _normalize_event_value(self, value):
        text = str(value)
        text = text.replace("\r", " ").replace("\n", " ")
        text = " ".join(text.split())
        return text if text else "-"

    def _log_event(self, event, **fields):
        self.logger.info(self._event_line(event, **fields))

    def _get_api(self):
        """获取API客户端"""
        if not self.api:
            self.api = self.auth_manager.get_api_client()
        return self.api

    def _next_url_kwargs(self, next_url, excluded_keys=None):
        """从 next_url 提取分页参数，并过滤掉已显式传入的参数"""
        if not next_url:
            return {}
        if excluded_keys is None:
            excluded_keys = set()
        import urllib.parse
        parsed = urllib.parse.urlparse(next_url)
        query_params = urllib.parse.parse_qs(parsed.query)
        return {
            k: v[0]
            for k, v in query_params.items()
            if v and k not in excluded_keys
        }

    def _notify_progress(self, phase, stats, message=None):
        """上报进度到上层状态管理"""
        if not self.progress_callback:
            return
        payload = {
            "phase": phase,
            "processed_total": stats.get("total", 0),
            "success": stats.get("success", 0),
            "skipped": stats.get("skipped", 0),
            "failed": stats.get("failed", 0),
            "hit_max_downloads": stats.get("hit_max_downloads", False),
            "rate_limited": stats.get("rate_limited", False),
            "last_error": stats.get("last_error"),
        }
        if message:
            payload["message"] = message
        self.progress_callback(payload)

    def _is_rate_limit_error(self, error_msg):
        """识别是否为限速/服务拥塞类错误"""
        msg = (error_msg or "").lower()
        keywords = [
            "rate limit",
            "too many requests",
            "temporarily unavailable",
            "http 429",
            "http 403",
            "http 500",
            "http 502",
            "http 503",
            "http 504",
            "status 429",
            "status 403",
            "status 500",
            "status 502",
            "status 503",
            "status 504",
        ]
        return any(k in msg for k in keywords)

    def _queue_sleep(self, processed_total):
        """按高速/低速队列节奏等待"""
        if self.high_speed_queue_size > 0 and processed_total <= self.high_speed_queue_size:
            return
        if self.low_speed_interval_seconds > 0:
            time.sleep(self.low_speed_interval_seconds)

    def _illust_url(self, illust_id):
        return f"https://www.pixiv.net/artworks/{illust_id}"

    def _with_illust_context(self, illust_id, error_msg):
        msg = (error_msg or "").strip()
        if not msg:
            msg = "未知错误"
        return f"pid={illust_id} url={self._illust_url(illust_id)} error={msg}"

    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _parse_time(self, value):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _json_safe(self, obj):
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))

    def _load_task_queue(self):
        if not self.task_queue_file.exists():
            return []
        try:
            with open(self.task_queue_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            items = data.get("items", []) if isinstance(data, dict) else []
            return items if isinstance(items, list) else []
        except Exception as e:
            self._log_event("queue_load_error", error=e)
            return []

    def _save_task_queue(self, items):
        payload = {
            "version": 1,
            "updated_at": self._now_str(),
            "items": items,
        }
        self.task_queue_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.task_queue_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _upsert_candidate(self, candidates, illust, is_bookmarked, is_following_author):
        illust_id = int(illust["id"])
        item = candidates.get(illust_id)
        if not item:
            copied = self._json_safe(illust)
            copied["is_bookmarked"] = bool(is_bookmarked)
            copied["is_following_author"] = bool(is_following_author)
            candidates[illust_id] = copied
            return

        item["is_bookmarked"] = bool(item.get("is_bookmarked", False) or is_bookmarked)
        item["is_following_author"] = bool(item.get("is_following_author", False) or is_following_author)

    def _scan_bookmarks(self, user_id, candidates):
        stats = {
            "scanned": 0,
            "filtered": 0,
            "rate_limited": False,
            "last_error": None,
        }
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        next_url = None
        self._log_event("scan_start", source="bookmarks", user_id=user_id)
        while True:
            try:
                if next_url:
                    page_result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict,
                        **self._next_url_kwargs(next_url, {"user_id", "restrict"})
                    )
                else:
                    page_result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict,
                    )
            except Exception as e:
                err = str(e)
                stats["last_error"] = err
                if self._is_rate_limit_error(err):
                    stats["rate_limited"] = True
                self._log_event("scan_error", source="bookmarks", error=err)
                break

            if not page_result or "illusts" not in page_result:
                break

            illusts = page_result.get("illusts", [])
            self._log_event("scan_page", source="bookmarks", page_size=len(illusts), next_url=bool(page_result.get("next_url")))
            for illust in illusts:
                stats["scanned"] += 1
                should_download, reason = self.config.should_download_illust(illust)
                if not should_download:
                    stats["filtered"] += 1
                    self._log_event("scan_filtered", source="bookmarks", illust_id=illust.get("id"), reason=reason)
                    continue
                self._upsert_candidate(candidates, illust, is_bookmarked=True, is_following_author=False)

            next_url = page_result.get("next_url")
            if not next_url:
                break

        self._log_event("scan_finish", source="bookmarks", scanned=stats["scanned"], filtered=stats["filtered"], rate_limited=stats["rate_limited"])
        return stats

    def _scan_following(self, user_id, candidates):
        stats = {
            "scanned": 0,
            "filtered": 0,
            "rate_limited": False,
            "last_error": None,
        }
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        following_users = []
        next_url = None
        self._log_event("scan_start", source="following", user_id=user_id)

        while True:
            try:
                if next_url:
                    page_result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict,
                        **self._next_url_kwargs(next_url, {"user_id", "restrict"})
                    )
                else:
                    page_result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict,
                    )
            except Exception as e:
                err = str(e)
                stats["last_error"] = err
                if self._is_rate_limit_error(err):
                    stats["rate_limited"] = True
                self._log_event("scan_error", source="following_users", error=err)
                return stats

            if page_result and "user_previews" in page_result:
                for user_preview in page_result["user_previews"]:
                    following_users.append(user_preview["user"]["id"])

            next_url = page_result.get("next_url") if page_result else None
            if not next_url:
                break

        self._log_event("following_users_loaded", user_count=len(following_users))
        for follow_user_id in following_users:
            try:
                result = api.user_illusts(user_id=int(follow_user_id))
            except Exception as e:
                err = str(e)
                stats["last_error"] = err
                if self._is_rate_limit_error(err):
                    stats["rate_limited"] = True
                    self._log_event("scan_error", source="following_illusts", follow_user_id=follow_user_id, error=err)
                    break
                self._log_event("scan_error", source="following_illusts", follow_user_id=follow_user_id, error=err)
                continue

            if not result or "illusts" not in result:
                continue

            illusts = result.get("illusts", [])
            self._log_event("scan_page", source="following", follow_user_id=follow_user_id, page_size=len(illusts))
            for illust in illusts:
                stats["scanned"] += 1
                should_download, reason = self.config.should_download_illust(illust)
                if not should_download:
                    stats["filtered"] += 1
                    self._log_event("scan_filtered", source="following", illust_id=illust.get("id"), reason=reason)
                    continue
                self._upsert_candidate(candidates, illust, is_bookmarked=False, is_following_author=True)

            if stats["rate_limited"]:
                break

        self._log_event("scan_finish", source="following", scanned=stats["scanned"], filtered=stats["filtered"], rate_limited=stats["rate_limited"])
        return stats

    def _merge_candidates_to_queue(self, candidates: Dict[int, dict]):
        items = self._load_task_queue()
        now = self._now_str()
        by_id = {int(i.get("illust_id")): i for i in items if i.get("illust_id") is not None}

        new_tasks = 0
        reset_tasks = 0
        skipped_downloaded = 0

        for illust_id, illust in candidates.items():
            if self.downloader.is_illust_fully_downloaded(illust):
                skipped_downloaded += 1
                existing = by_id.get(illust_id)
                if existing:
                    existing["status"] = "done"
                    existing["updated_at"] = now
                    existing["is_bookmarked"] = bool(illust.get("is_bookmarked", False))
                    existing["is_following_author"] = bool(illust.get("is_following_author", False))
                    existing["illust"] = illust
                continue

            existing = by_id.get(illust_id)
            if not existing:
                by_id[illust_id] = {
                    "illust_id": illust_id,
                    "status": "pending",
                    "retry_count": 0,
                    "last_error": None,
                    "next_retry_at": None,
                    "is_bookmarked": bool(illust.get("is_bookmarked", False)),
                    "is_following_author": bool(illust.get("is_following_author", False)),
                    "enqueued_at": now,
                    "updated_at": now,
                    "illust": illust,
                }
                new_tasks += 1
                self._log_event("enqueue", illust_id=illust_id, status="new")
                continue

            prev_status = existing.get("status")
            existing["illust"] = illust
            existing["is_bookmarked"] = bool(illust.get("is_bookmarked", False) or existing.get("is_bookmarked", False))
            existing["is_following_author"] = bool(illust.get("is_following_author", False) or existing.get("is_following_author", False))
            existing["updated_at"] = now
            if prev_status in ("done", "running"):
                existing["status"] = "pending"
                existing["next_retry_at"] = None
                existing["last_error"] = None
                reset_tasks += 1
                self._log_event("enqueue", illust_id=illust_id, status="reset_pending", prev_status=prev_status)

        merged_items = sorted(by_id.values(), key=lambda x: int(x.get("illust_id", 0)))
        self._save_task_queue(merged_items)
        self._log_event("queue_merged", candidates=len(candidates), new_tasks=new_tasks, reset_tasks=reset_tasks, skipped_downloaded=skipped_downloaded, queue_size=len(merged_items))
        return {
            "new_tasks": new_tasks,
            "reset_tasks": reset_tasks,
            "skipped_downloaded": skipped_downloaded,
            "queue_size": len(merged_items),
        }

    def _is_task_ready(self, item, now):
        status = item.get("status")
        if status in ("pending", "running"):
            return True
        if status == "failed":
            next_retry_at = self._parse_time(item.get("next_retry_at"))
            if next_retry_at is None:
                return True
            return now >= next_retry_at
        return False

    def _next_retry_seconds(self, retry_count):
        # 指数退避，最长 1 小时
        safe_retry = max(1, int(retry_count))
        return min(3600, 60 * (2 ** min(6, safe_retry - 1)))

    def _consume_task_queue(self, max_downloads):
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "hit_max_downloads": False,
            "rate_limited": False,
            "last_error": None,
        }
        items = self._load_task_queue()
        now = datetime.now()
        downloaded_count = 0

        self._log_event("queue_consume_start", queue_size=len(items), max_downloads=max_downloads)
        for item in items:
            if max_downloads > 0 and downloaded_count >= max_downloads:
                stats["hit_max_downloads"] = True
                break

            if not self._is_task_ready(item, now):
                continue

            illust = item.get("illust") or {}
            illust_id = item.get("illust_id")
            if not illust_id:
                continue

            illust["is_bookmarked"] = bool(item.get("is_bookmarked", False))
            illust["is_following_author"] = bool(item.get("is_following_author", False))

            if self.downloader.is_illust_fully_downloaded(illust):
                item["status"] = "done"
                item["updated_at"] = self._now_str()
                stats["skipped"] += 1
                stats["total"] += 1
                self._log_event("dequeue", illust_id=illust_id, status="skip_already_downloaded")
                self._save_task_queue(items)
                self._notify_progress("download_queue", stats)
                continue

            prev_status = item.get("status")
            item["status"] = "running"
            item["updated_at"] = self._now_str()
            self._save_task_queue(items)
            self._log_event("dequeue", illust_id=illust_id, prev_status=prev_status, status="running")

            dl_result = self._download_illust(illust)
            stats["total"] += 1
            if dl_result.get("success"):
                item["status"] = "done"
                item["last_error"] = None
                item["next_retry_at"] = None
                item["updated_at"] = self._now_str()
                stats["success"] += 1
                downloaded_count += 1
                self._log_event("task_result", illust_id=illust_id, status="success")
            elif dl_result.get("skipped", False):
                item["status"] = "done"
                item["last_error"] = None
                item["next_retry_at"] = None
                item["updated_at"] = self._now_str()
                stats["skipped"] += 1
                self._log_event("task_result", illust_id=illust_id, status="skipped")
            else:
                err = dl_result.get("error") or "未知错误"
                retry_count = int(item.get("retry_count", 0)) + 1
                wait_seconds = self._next_retry_seconds(retry_count)
                next_retry_at = datetime.now() + timedelta(seconds=wait_seconds)

                item["status"] = "failed"
                item["retry_count"] = retry_count
                item["last_error"] = err
                item["next_retry_at"] = next_retry_at.strftime("%Y-%m-%d %H:%M:%S")
                item["updated_at"] = self._now_str()

                stats["failed"] += 1
                stats["last_error"] = err
                self._log_event("task_result", illust_id=illust_id, status="failed", retry_count=retry_count, next_retry_at=item["next_retry_at"], error=err)
                if self._is_rate_limit_error(err):
                    stats["rate_limited"] = True

            self._save_task_queue(items)
            self._notify_progress("download_queue", stats)

            if stats["rate_limited"]:
                break
            if stats["hit_max_downloads"]:
                break

            if not dl_result.get("skipped", False):
                self._queue_sleep(stats["total"])

        self._log_event(
            "queue_consume_finish",
            success=stats["success"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            total=stats["total"],
            hit_max_downloads=stats["hit_max_downloads"],
            rate_limited=stats["rate_limited"],
        )
        return stats

    def _merge_stats(self, base, part):
        for key in ("success", "failed", "skipped", "total"):
            base[key] = base.get(key, 0) + int(part.get(key, 0) or 0)
        base["hit_max_downloads"] = base.get("hit_max_downloads", False) or bool(part.get("hit_max_downloads", False))
        base["rate_limited"] = base.get("rate_limited", False) or bool(part.get("rate_limited", False))
        if part.get("last_error"):
            base["last_error"] = part.get("last_error")

    def sync_with_task_queue(self, user_id, download_mode, max_downloads):
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "hit_max_downloads": False,
            "rate_limited": False,
            "last_error": None,
        }
        self._log_event("sync_cycle_start", user_id=user_id, download_mode=download_mode, max_downloads=max_downloads)
        self._notify_progress("scan", stats, "开始扫描新作品")

        candidates = {}
        scan_errors = []

        if download_mode in ["bookmarks", "both"]:
            bookmark_scan = self._scan_bookmarks(user_id, candidates)
            if bookmark_scan.get("last_error"):
                scan_errors.append(bookmark_scan.get("last_error"))
            if bookmark_scan.get("rate_limited"):
                stats["rate_limited"] = True

        if download_mode in ["following", "both"] and not stats.get("rate_limited"):
            following_scan = self._scan_following(user_id, candidates)
            if following_scan.get("last_error"):
                scan_errors.append(following_scan.get("last_error"))
            if following_scan.get("rate_limited"):
                stats["rate_limited"] = True

        if scan_errors:
            stats["last_error"] = scan_errors[-1]

        merge_info = self._merge_candidates_to_queue(candidates)
        self._notify_progress(
            "queue_build",
            stats,
            f"扫描完成，候选 {len(candidates)}，新增任务 {merge_info['new_tasks']}，队列 {merge_info['queue_size']}",
        )

        queue_stats = self._consume_task_queue(max_downloads)
        self._merge_stats(stats, queue_stats)
        self._notify_progress("done", stats, "任务队列处理完成")
        self._log_event(
            "sync_cycle_finish",
            success=stats["success"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            total=stats["total"],
            rate_limited=stats["rate_limited"],
            hit_max_downloads=stats["hit_max_downloads"],
            queue_size=merge_info.get("queue_size", 0),
        )
        return stats

    def _download_illust(self, illust):
        """下载单个作品"""
        illust_id = illust["id"]
        illust_type = illust.get("type", "illust")

        self.logger.info(f"下载作品 {illust_id}: {illust['title']}")
        self._log_event("download_start", illust_id=illust_id, illust_type=illust_type, title=illust.get("title", ""))

        try:
            # 保存到数据库
            self.database.save_illust(illust)

            # 根据类型下载
            if illust_type == "ugoira":
                # 动图需要特殊处理
                api = self._get_api()
                ugoira_info = api.ugoira_metadata(illust_id)

                if ugoira_info and "ugoira_metadata" in ugoira_info:
                    result = self.downloader.download_ugoira(illust, ugoira_info["ugoira_metadata"])
                else:
                    return {
                        "success": False,
                        "error": self._with_illust_context(illust_id, "无法获取动图信息")
                    }
            else:
                # 静态图片：优先下载原图，支持多图逐页下载
                result = self._download_illust_images(illust)

            # 处理下载结果
            if result["success"]:
                if not self.downloader.is_illust_fully_downloaded(illust):
                    incomplete_error = self._with_illust_context(illust_id, "文件未完整下载（存在缺页或缺失文件）")
                    self.database.record_download_error(illust_id, incomplete_error)
                    self._log_event("download_finish", illust_id=illust_id, status="failed", error=incomplete_error)
                    return {"success": False, "error": incomplete_error}
                # 标记为已下载
                file_size = result.get("file_size")
                self.database.mark_as_downloaded(illust_id, result["file_path"], file_size)
                self.logger.info(f"作品 {illust_id} 下载成功: {result['file_path']}")
                self._log_event("download_finish", illust_id=illust_id, status="success", file_path=result.get("file_path", ""))
            elif result.get("skipped", False):
                # 标记为已下载（因为已存在）
                self.database.mark_as_downloaded(illust_id, "已存在", 0)
                self._log_event("download_finish", illust_id=illust_id, status="skipped", reason=result.get("message", "exists"))
            else:
                if result.get("error"):
                    result["error"] = self._with_illust_context(illust_id, result.get("error"))
                self._log_event("download_finish", illust_id=illust_id, status="failed", error=result.get("error", "unknown"))

            return result

        except Exception as e:
            error_msg = self._with_illust_context(illust_id, f"下载失败: {str(e)}")
            self.logger.error(f"作品 {illust_id} {error_msg}")
            try:
                self.database.record_download_error(illust_id, error_msg)
            except Exception as db_error:
                self._log_event("db_record_error_failed", illust_id=illust_id, error=db_error)
            self._log_event("download_finish", illust_id=illust_id, status="failed", error=error_msg)
            return {"success": False, "error": error_msg}

    def _download_illust_images(self, illust):
        """下载静态作品图片（优先原图）"""
        # 多图作品：优先使用 meta_pages[].image_urls.original
        meta_pages = illust.get("meta_pages") or []
        if isinstance(meta_pages, list) and len(meta_pages) > 0:
            total_size = 0
            downloaded = 0
            first_path = None

            for idx, page in enumerate(meta_pages):
                image_urls = page.get("image_urls", {}) if isinstance(page, dict) else {}
                image_url = image_urls.get("original") or image_urls.get("large")
                if not image_url:
                    continue

                r = self.downloader.download_image(image_url, illust, page_index=idx)
                if not r.get("success") and not r.get("skipped", False):
                    err = r.get("error") or "下载失败"
                    return {"success": False, "error": f"page_index={idx} image_url={image_url} {err}"}

                downloaded += 1
                total_size += r.get("file_size", 0) or 0
                if not first_path:
                    first_path = r.get("file_path")

            if downloaded == 0:
                return {"success": False, "error": "未找到可下载图片链接"}
            return {
                "success": True,
                "file_path": first_path or "",
                "file_size": total_size,
                "message": f"多图下载成功: {downloaded} 页"
            }

        # 单图作品：优先 meta_single_page.original_image_url，回退 large
        single = illust.get("meta_single_page", {}) if isinstance(illust.get("meta_single_page"), dict) else {}
        image_url = single.get("original_image_url")
        if not image_url:
            image_url = illust.get("image_urls", {}).get("original") or illust.get("image_urls", {}).get("large")
        if not image_url:
            return {"success": False, "error": "未找到可下载图片链接"}

        result = self.downloader.download_image(image_url, illust)
        if result.get("skipped", False):
            return {"success": True, "file_path": result.get("file_path", ""), "file_size": result.get("file_size", 0), "message": "已存在"}
        if not result.get("success"):
            err = result.get("error") or "下载失败"
            return {"success": False, "error": f"page_index=0 image_url={image_url} {err}"}
        return result

    def test_connection(self):
        """测试连接"""
        try:
            api = self._get_api()

            # 测试获取用户信息
            user_id = self.config.get_user_id()
            if user_id:
                user_info = api.user_detail(int(user_id))
                if user_info and "user" in user_info:
                    return {
                        "success": True,
                        "user_name": user_info["user"]["name"],
                        "account": user_info["user"]["account"]
                    }

            return {"success": True, "message": "连接成功"}

        except Exception as e:
            return {"success": False, "error": str(e)}
