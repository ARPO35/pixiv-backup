import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "pixiv-backup"))

from modules.crawler import PixivCrawler


class DummyConfig:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)

    def get_high_speed_queue_size(self):
        return 0

    def get_low_speed_interval_seconds(self):
        return 0

    def get_interval_jitter_ms(self):
        return 0

    def get_data_dir(self):
        return self.base_dir / "data"

    def get_metadata_dir(self):
        return self.base_dir / "metadata"

    def get_restrict_mode(self):
        return "public"

    def should_download_illust(self, illust_info):
        del illust_info
        return True, "ok"


class DummyAuthManager:
    def __init__(self, api):
        self.api = api

    def get_api_client(self):
        return self.api


class DummyDatabase:
    def save_illust(self, illust):
        del illust


class DummyDownloader:
    def is_access_limited_illust(self, illust):
        del illust
        return False

    def is_illust_fully_downloaded(self, illust):
        del illust
        return False


class RecordingDatabase(DummyDatabase):
    def __init__(self):
        self.marked_not_downloaded = []
        self.recorded_errors = []

    def mark_as_not_downloaded(self, illust_id):
        self.marked_not_downloaded.append(illust_id)

    def record_download_error(self, illust_id, error_message):
        self.recorded_errors.append((illust_id, error_message))


class FakeFollowingApi:
    def __init__(self, author_pages):
        self.author_pages = author_pages
        self.user_illusts_calls = []

    def user_following(self, user_id, restrict):
        del user_id, restrict
        return {
            "user_previews": [{"user": {"id": author_id}} for author_id in self.author_pages],
            "next_url": None,
        }

    def user_illusts(self, user_id, **kwargs):
        self.user_illusts_calls.append((user_id, dict(kwargs)))
        pages = self.author_pages[user_id]
        if not kwargs:
            return pages[0]
        offset = int(kwargs.get("offset", 0))
        return pages[offset]


class CrawlerFollowingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)

    def _crawler(self, api):
        config = DummyConfig(self.tempdir.name)
        return PixivCrawler(
            config,
            DummyAuthManager(api),
            DummyDatabase(),
            DummyDownloader(),
        )

    def _illust(self, illust_id, created_at):
        return {
            "id": illust_id,
            "title": f"illust {illust_id}",
            "create_date": created_at,
        }

    def test_scan_following_fetches_all_author_pages(self):
        api = FakeFollowingApi({
            10: {
                0: {
                    "illusts": [
                        self._illust(300, "2024-01-03T00:00:00+00:00"),
                        self._illust(299, "2024-01-02T00:00:00+00:00"),
                    ],
                    "next_url": "https://app-api.pixiv.net/v1/user/illusts?user_id=10&offset=1",
                },
                1: {
                    "illusts": [self._illust(298, "2024-01-01T00:00:00+00:00")],
                    "next_url": None,
                },
            },
        })
        crawler = self._crawler(api)
        candidates = {}

        stats = crawler._scan_following("1", candidates, full_scan=True, scan_cursor={})

        self.assertEqual(stats["scanned"], 3)
        self.assertEqual(sorted(candidates), [298, 299, 300])
        self.assertEqual(api.user_illusts_calls, [(10, {}), (10, {"offset": "1"})])

    def test_scan_following_stops_current_author_after_incremental_cursor_hit(self):
        api = FakeFollowingApi({
            10: {
                0: {
                    "illusts": [
                        self._illust(300, "2024-01-03T00:00:00+00:00"),
                        self._illust(299, "2024-01-02T00:00:00+00:00"),
                    ],
                    "next_url": "https://app-api.pixiv.net/v1/user/illusts?user_id=10&offset=1",
                },
                1: {
                    "illusts": [self._illust(298, "2024-01-01T00:00:00+00:00")],
                    "next_url": None,
                },
            },
        })
        crawler = self._crawler(api)
        candidates = {}
        scan_cursor = {"following": {"authors": {"10": {"latest_seen_illust_id": 299}}}}

        stats = crawler._scan_following("1", candidates, full_scan=False, scan_cursor=scan_cursor)

        self.assertEqual(stats["scanned"], 1)
        self.assertEqual(sorted(candidates), [300])
        self.assertEqual(api.user_illusts_calls, [(10, {})])

    def test_download_failure_clears_downloaded_state_before_recording_error(self):
        api = FakeFollowingApi({})
        database = RecordingDatabase()
        crawler = PixivCrawler(
            DummyConfig(self.tempdir.name),
            DummyAuthManager(api),
            database,
            DummyDownloader(),
        )
        crawler._download_illust_images = lambda illust: {"success": False, "error": "network failed"}

        result = crawler._download_illust(self._illust(300, "2024-01-03T00:00:00+00:00"))

        self.assertFalse(result["success"])
        self.assertEqual(database.marked_not_downloaded, [300])
        self.assertEqual(len(database.recorded_errors), 1)
        self.assertEqual(database.recorded_errors[0][0], 300)
        self.assertIn("network failed", database.recorded_errors[0][1])


if __name__ == "__main__":
    unittest.main()
