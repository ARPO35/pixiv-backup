import time
import logging
from typing import Dict, List

class PixivCrawler:
    def __init__(self, config, auth_manager, database, downloader):
        """初始化爬虫"""
        self.config = config
        self.auth_manager = auth_manager
        self.database = database
        self.downloader = downloader
        self.api = None
        self.logger = logging.getLogger(__name__)
        
    def _get_api(self):
        """获取API客户端"""
        if not self.api:
            self.api = self.auth_manager.get_api_client()
        return self.api
        
    def download_user_bookmarks(self, user_id):
        """下载用户收藏"""
        self.logger.info(f"开始下载用户 {user_id} 的收藏...")
        
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        max_downloads = self.config.get_max_downloads()
        
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0
        }
        
        try:
            # 获取收藏列表
            next_url = None
            downloaded_count = 0
            
            while True:
                # 限制最大下载数量
                if max_downloads > 0 and downloaded_count >= max_downloads:
                    self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                    break
                    
                # 获取下一页
                if next_url:
                    # 解析next_url参数
                    import urllib.parse
                    parsed = urllib.parse.urlparse(next_url)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    
                    # 调用API
                    result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict,
                        **{k: v[0] for k, v in query_params.items() if v}
                    )
                else:
                    # 第一页
                    result = api.user_bookmarks_illust(
                        user_id=int(user_id),
                        restrict=restrict
                    )
                    
                if not result or "illusts" not in result:
                    self.logger.warning("没有获取到作品列表")
                    break
                    
                illusts = result.get("illusts", [])
                self.logger.info(f"获取到 {len(illusts)} 个作品")
                
                # 处理每个作品
                for illust in illusts:
                    stats["total"] += 1
                    
                    # 检查过滤条件
                    should_download, reason = self.config.should_download_illust(illust)
                    if not should_download:
                        self.logger.info(f"跳过作品 {illust['id']}: {reason}")
                        stats["skipped"] += 1
                        continue
                        
                    # 下载作品
                    result = self._download_illust(illust)
                    if result["success"]:
                        stats["success"] += 1
                        downloaded_count += 1
                    elif result.get("skipped", False):
                        stats["skipped"] += 1
                    else:
                        stats["failed"] += 1
                        
                    # 限制最大下载数量
                    if max_downloads > 0 and downloaded_count >= max_downloads:
                        self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                        break
                        
                    # 延迟防止限制
                    time.sleep(1.5)
                    
                # 检查是否有下一页
                next_url = result.get("next_url")
                if not next_url:
                    break
                    
                self.logger.info("获取下一页...")
                
        except Exception as e:
            self.logger.error(f"下载收藏时发生错误: {str(e)}", exc_info=True)
            
        self.logger.info(f"收藏下载完成: 成功 {stats['success']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}")
        return stats
        
    def download_following_illusts(self, user_id):
        """下载关注用户的作品"""
        self.logger.info(f"开始下载用户 {user_id} 的关注用户作品...")
        
        api = self._get_api()
        restrict = self.config.get_restrict_mode()
        max_downloads = self.config.get_max_downloads()
        
        stats = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0
        }
        
        try:
            # 获取关注用户列表
            following_users = []
            next_url = None
            
            while True:
                if next_url:
                    # 解析next_url参数
                    import urllib.parse
                    parsed = urllib.parse.urlparse(next_url)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    
                    result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict,
                        **{k: v[0] for k, v in query_params.items() if v}
                    )
                else:
                    result = api.user_following(
                        user_id=int(user_id),
                        restrict=restrict
                    )
                    
                if result and "user_previews" in result:
                    for user_preview in result["user_previews"]:
                        following_users.append(user_preview["user"]["id"])
                        
                next_url = result.get("next_url")
                if not next_url:
                    break
                    
            self.logger.info(f"获取到 {len(following_users)} 个关注用户")
            
            # 下载每个关注用户的作品
            downloaded_count = 0
            
            for user_id in following_users:
                # 获取用户的最新作品
                result = api.user_illusts(user_id=int(user_id))
                
                if not result or "illusts" not in result:
                    continue
                    
                illusts = result.get("illusts", [])
                self.logger.info(f"用户 {user_id} 有 {len(illusts)} 个作品")
                
                # 处理每个作品
                for illust in illusts:
                    stats["total"] += 1
                    
                    # 检查过滤条件
                    should_download, reason = self.config.should_download_illust(illust)
                    if not should_download:
                        self.logger.info(f"跳过作品 {illust['id']}: {reason}")
                        stats["skipped"] += 1
                        continue
                        
                    # 下载作品
                    result = self._download_illust(illust)
                    if result["success"]:
                        stats["success"] += 1
                        downloaded_count += 1
                    elif result.get("skipped", False):
                        stats["skipped"] += 1
                    else:
                        stats["failed"] += 1
                        
                    # 限制最大下载数量
                    if max_downloads > 0 and downloaded_count >= max_downloads:
                        self.logger.info(f"达到最大下载数量限制: {max_downloads}")
                        break
                        
                    # 延迟防止限制
                    time.sleep(1.5)
                    
                # 检查是否达到限制
                if max_downloads > 0 and downloaded_count >= max_downloads:
                    break
                    
        except Exception as e:
            self.logger.error(f"下载关注用户作品时发生错误: {str(e)}", exc_info=True)
            
        self.logger.info(f"关注用户作品下载完成: 成功 {stats['success']}, 跳过 {stats['skipped']}, 失败 {stats['failed']}")
        return stats
        
    def _download_illust(self, illust):
        """下载单个作品"""
        illust_id = illust["id"]
        illust_type = illust.get("type", "illust")
        
        self.logger.info(f"下载作品 {illust_id}: {illust['title']}")
        
        try:
            # 保存到数据库
            self.database.save_illust(illust)
            
            # 检查是否已下载
            if self.database.is_downloaded(illust_id):
                self.logger.info(f"作品 {illust_id} 已下载，跳过")
                return {"success": False, "skipped": True, "message": "已存在"}
                
            # 根据类型下载
            if illust_type == "ugoira":
                # 动图需要特殊处理
                api = self._get_api()
                ugoira_info = api.ugoira_metadata(illust_id)
                
                if ugoira_info and "ugoira_metadata" in ugoira_info:
                    result = self.downloader.download_ugoira(illust, ugoira_info["ugoira_metadata"])
                else:
                    return {"success": False, "error": "无法获取动图信息"}
            else:
                # 静态图片
                image_url = illust["image_urls"]["large"]
                result = self.downloader.download_image(image_url, illust)
                
            # 处理下载结果
            if result["success"]:
                # 标记为已下载
                file_size = result.get("file_size")
                self.database.mark_as_downloaded(illust_id, result["file_path"], file_size)
                self.logger.info(f"作品 {illust_id} 下载成功: {result['file_path']}")
            elif result.get("skipped", False):
                # 标记为已下载（因为已存在）
                self.database.mark_as_downloaded(illust_id, "已存在", 0)
                
            return result
            
        except Exception as e:
            error_msg = f"下载失败: {str(e)}"
            self.logger.error(f"作品 {illust_id} {error_msg}")
            self.database.record_download_error(illust_id, error_msg)
            return {"success": False, "error": error_msg}
            
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