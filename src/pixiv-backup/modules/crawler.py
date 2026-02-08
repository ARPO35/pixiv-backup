import time
import logging
from typing import Dict, List

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
        self._log_event(
            "crawler_init",
            high_speed_queue_size=self.high_speed_queue_size,
            low_speed_interval_seconds=self.low_speed_interval_seconds,
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
        
    def download_user_bookmarks(self, user_id, max_downloads_override=None):
        """下载用户收藏"""
        self.logger.info(f"开始下载用户 {user_id} 的收藏...")
        self._log_event("scan_start", source="bookmarks", user_id=user_id)
        
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        max_downloads = self.config.get_max_downloads() if max_downloads_override is None else max_downloads_override
        
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "hit_max_downloads": False,
            "rate_limited": False,
            "last_error": None
        }
        self._notify_progress("bookmarks", stats, "开始同步收藏")
        
        try:
            # 获取收藏列表
            next_url = None
            downloaded_count = 0
            
            while True:
                # 限制最大下载数量
                if max_downloads > 0 and downloaded_count >= max_downloads:
                    self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                    stats["hit_max_downloads"] = True
                    break
                    
                # 获取下一页
                if next_url:
                    page_result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict,
                        **self._next_url_kwargs(next_url, {"user_id", "restrict"})
                    )
                else:
                    # 第一页
                    page_result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict
                    )
                    
                if not page_result or "illusts" not in page_result:
                    self.logger.warning("没有获取到作品列表")
                    break
                    
                illusts = page_result.get("illusts", [])
                self.logger.info(f"获取到 {len(illusts)} 个作品")
                self._log_event("scan_page", source="bookmarks", page_size=len(illusts), next_url=bool(page_result.get("next_url")))
                
                # 处理每个作品
                for illust in illusts:
                    stats["total"] += 1
                    
                    # 检查过滤条件
                    should_download, reason = self.config.should_download_illust(illust)
                    if not should_download:
                        self.logger.info(f"跳过作品 {illust['id']}: {reason}")
                        self._log_event("skip_illust", source="bookmarks", illust_id=illust["id"], reason=reason)
                        stats["skipped"] += 1
                        continue
                        
                    # 下载作品
                    dl_result = self._download_illust(illust)
                    if dl_result["success"]:
                        stats["success"] += 1
                        downloaded_count += 1
                        self._log_event("download_result", source="bookmarks", illust_id=illust["id"], status="success")
                    elif dl_result.get("skipped", False):
                        stats["skipped"] += 1
                        self._log_event("download_result", source="bookmarks", illust_id=illust["id"], status="skipped")
                    else:
                        stats["failed"] += 1
                        self._log_event("download_result", source="bookmarks", illust_id=illust["id"], status="failed")
                        err = dl_result.get("error")
                        if err:
                            stats["last_error"] = err
                            if self._is_rate_limit_error(err):
                                stats["rate_limited"] = True
                                self._notify_progress("bookmarks", stats, f"检测到限速/服务异常: {err}")
                                break

                    self._notify_progress("bookmarks", stats)
                        
                    # 限制最大下载数量
                    if max_downloads > 0 and downloaded_count >= max_downloads:
                        self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                        stats["hit_max_downloads"] = True
                        break
                        
                    # 高低速队列节奏：跳过项不等待（未发起下载请求）
                    if not dl_result.get("skipped", False):
                        self._queue_sleep(stats["total"])

                if stats.get("rate_limited"):
                    break
                if stats.get("hit_max_downloads"):
                    break
                    
                # 检查是否有下一页
                next_url = page_result.get("next_url")
                if not next_url:
                    break
                    
                self.logger.info("获取下一页...")
                
        except Exception as e:
            self.logger.error(f"下载收藏时发生错误: {str(e)}", exc_info=True)
            stats["last_error"] = str(e)
            if self._is_rate_limit_error(str(e)):
                stats["rate_limited"] = True
            
        self.logger.info(f"收藏下载完成: 成功 {stats['success']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}")
        self._log_event(
            "scan_finish",
            source="bookmarks",
            success=stats["success"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            total=stats["total"],
            rate_limited=stats.get("rate_limited", False),
        )
        self._notify_progress("bookmarks", stats, "收藏同步结束")
        return stats
        
    def download_following_illusts(self, user_id, max_downloads_override=None):
        """下载关注用户的作品"""
        self.logger.info(f"开始下载用户 {user_id} 的关注用户作品...")
        self._log_event("scan_start", source="following", user_id=user_id)
        
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        max_downloads = self.config.get_max_downloads() if max_downloads_override is None else max_downloads_override
        
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "hit_max_downloads": False,
            "rate_limited": False,
            "last_error": None
        }
        self._notify_progress("following", stats, "开始同步关注作品")
        
        try:
            # 获取关注用户列表
            following_users = []
            next_url = None
            
            while True:
                if next_url:
                    page_result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict,
                        **self._next_url_kwargs(next_url, {"user_id", "restrict"})
                    )
                else:
                    page_result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict
                    )
                    
                if page_result and "user_previews" in page_result:
                    for user_preview in page_result["user_previews"]:
                        following_users.append(user_preview["user"]["id"])
                        
                next_url = page_result.get("next_url")
                if not next_url:
                    break
                    
            self.logger.info(f"获取到 {len(following_users)} 个关注用户")
            self._log_event("following_users_loaded", user_count=len(following_users))
            
            # 下载每个关注用户的作品
            downloaded_count = 0
            
            for follow_user_id in following_users:
                # 获取用户的最新作品
                result = api.user_illusts(user_id=int(follow_user_id))
                
                if not result or "illusts" not in result:
                    continue
                    
                illusts = result.get("illusts", [])
                self.logger.info(f"用户 {follow_user_id} 有 {len(illusts)} 个作品")
                self._log_event("scan_page", source="following", follow_user_id=follow_user_id, page_size=len(illusts))
                
                # 处理每个作品
                for illust in illusts:
                    stats["total"] += 1
                    
                    # 检查过滤条件
                    should_download, reason = self.config.should_download_illust(illust)
                    if not should_download:
                        self.logger.info(f"跳过作品 {illust['id']}: {reason}")
                        self._log_event("skip_illust", source="following", illust_id=illust["id"], reason=reason)
                        stats["skipped"] += 1
                        continue
                        
                    # 下载作品
                    dl_result = self._download_illust(illust)
                    if dl_result["success"]:
                        stats["success"] += 1
                        downloaded_count += 1
                        self._log_event("download_result", source="following", illust_id=illust["id"], status="success")
                    elif dl_result.get("skipped", False):
                        stats["skipped"] += 1
                        self._log_event("download_result", source="following", illust_id=illust["id"], status="skipped")
                    else:
                        stats["failed"] += 1
                        self._log_event("download_result", source="following", illust_id=illust["id"], status="failed")
                        err = dl_result.get("error")
                        if err:
                            stats["last_error"] = err
                            if self._is_rate_limit_error(err):
                                stats["rate_limited"] = True
                                self._notify_progress("following", stats, f"检测到限速/服务异常: {err}")
                                break

                    self._notify_progress("following", stats)
                        
                    # 限制最大下载数量
                    if max_downloads > 0 and downloaded_count >= max_downloads:
                        self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                        stats["hit_max_downloads"] = True
                        break
                        
                    # 高低速队列节奏：跳过项不等待（未发起下载请求）
                    if not dl_result.get("skipped", False):
                        self._queue_sleep(stats["total"])

                if stats.get("rate_limited"):
                    break
                    
                # 检查是否达到限制
                if max_downloads > 0 and downloaded_count >= max_downloads:
                    stats["hit_max_downloads"] = True
                    break
                if stats.get("rate_limited"):
                    break
                    
        except Exception as e:
            self.logger.error(f"下载关注用户作品时发生错误: {str(e)}", exc_info=True)
            stats["last_error"] = str(e)
            if self._is_rate_limit_error(str(e)):
                stats["rate_limited"] = True
            
        self.logger.info(f"关注用户作品下载完成: 成功 {stats['success']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}")
        self._log_event(
            "scan_finish",
            source="following",
            success=stats["success"],
            skipped=stats["skipped"],
            failed=stats["failed"],
            total=stats["total"],
            rate_limited=stats.get("rate_limited", False),
        )
        self._notify_progress("following", stats, "关注作品同步结束")
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
            
            # 检查是否已下载
            if self.database.is_downloaded(illust_id):
                self.logger.info(f"作品 {illust_id} 已下载，跳过")
                self._log_event("download_skip", illust_id=illust_id, reason="database_downloaded")
                return {"success": False, "skipped": True, "message": "已存在"}
                
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
            self.database.record_download_error(illust_id, error_msg)
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
                if not r.get("success"):
                    return r
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

        return self.downloader.download_image(image_url, illust)
            
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
