import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src" / "pixiv-backup"))

from modules.downloader import DownloadManager


class DummyConfig:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)

    def get_timeout(self):
        return 12

    def get_image_dir(self):
        return self.base_dir / "img"

    def get_metadata_dir(self):
        return self.base_dir / "metadata"


class FakeResponse:
    def __init__(self, chunks=None, status_code=200):
        self._chunks = list(chunks or [])
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            exc = RuntimeError(f"{self.status_code} error")
            exc.response = self
            raise exc

    def iter_content(self, chunk_size=8192):
        del chunk_size
        for chunk in self._chunks:
            yield chunk


class DownloaderUgoiraTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.config = DummyConfig(self.tempdir.name)
        self.downloader = DownloadManager(self.config)
        self.illust_info = {
            "id": 123456,
            "title": "ugoira test",
            "caption": "",
            "user": {
                "id": 1,
                "name": "tester",
                "account": "tester",
                "profile_image_urls": {"medium": ""},
            },
            "type": "ugoira",
            "tags": [],
            "image_urls": {},
        }

    def _load_metadata(self):
        metadata_path = self.config.get_metadata_dir() / "123456.json"
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def test_download_ugoira_prefers_api_transport_and_app_api_referer(self):
        api_client = Mock()
        api_client.requests = Mock()
        api_client.requests_kwargs = {"timeout": 9}
        api_client.requests.get.return_value = FakeResponse([b"abc", b"123"])

        result = self.downloader.download_ugoira(
            self.illust_info,
            {
                "frames": [{"file": "000000.jpg", "delay": 60}],
                "zip_urls": {
                    "original": "https://i.pximg.net/img-zip-ugoira/img/2024/01/01/00/00/00/123456_ugoira1920x1080.zip"
                },
            },
            api_client=api_client,
        )

        self.assertTrue(result["success"])
        api_client.requests.get.assert_called_once_with(
            "https://i.pximg.net/img-zip-ugoira/img/2024/01/01/00/00/00/123456_ugoira1920x1080.zip",
            headers={"Referer": "https://app-api.pixiv.net/"},
            stream=True,
            timeout=9,
        )
        zip_path = self.config.get_image_dir() / "123456" / "123456.zip"
        self.assertEqual(zip_path.read_bytes(), b"abc123")
        metadata = self._load_metadata()
        self.assertEqual(metadata["ugoira_zip_url"], "https://i.pximg.net/img-zip-ugoira/img/2024/01/01/00/00/00/123456_ugoira1920x1080.zip")
        self.assertEqual(metadata["ugoira_frames"], [{"file": "000000.jpg", "delay": 60}])

    def test_download_ugoira_falls_back_to_session_when_api_client_missing(self):
        self.downloader.session.get = Mock(return_value=FakeResponse([b"zipdata"]))

        result = self.downloader.download_ugoira(
            self.illust_info,
            {"zip_url": "https://i.pximg.net/img-zip-ugoira/example.zip", "frames": []},
        )

        self.assertTrue(result["success"])
        self.downloader.session.get.assert_called_once_with(
            "https://i.pximg.net/img-zip-ugoira/example.zip",
            timeout=12,
            stream=True,
        )

    def test_download_ugoira_preserves_http_status_on_failure(self):
        api_client = Mock()
        api_client.requests = Mock()
        api_client.requests_kwargs = {}
        api_client.requests.get.return_value = FakeResponse(status_code=403)

        result = self.downloader.download_ugoira(
            self.illust_info,
            {"zip_url": "https://i.pximg.net/img-zip-ugoira/example.zip", "frames": []},
            api_client=api_client,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["http_status"], 403)


if __name__ == "__main__":
    unittest.main()
