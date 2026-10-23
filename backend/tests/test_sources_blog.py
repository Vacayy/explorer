"""블로그 소스 추가 라우트 — 본문 {url}을 받는다(도우미가 라우트를 가로채 늘 422였던 회귀, 2026-10-23)."""
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import spine_sources


class BlogRouteTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(spine_sources.router)
        self.client = TestClient(app)

    def test_route_is_add_blog(self):
        route = next(r for r in spine_sources.router.routes if r.path.endswith("/blog") and "POST" in r.methods)
        self.assertIs(route.endpoint, spine_sources.add_blog)

    def test_youtube_url_gets_readable_message(self):
        r = self.client.post("/api/spine/sources/blog", json={"url": "https://www.youtube.com/@somechannel"})
        self.assertEqual(r.status_code, 422)
        self.assertIsInstance(r.json()["detail"], str)          # 문자열 — 화면이 그대로 보여 줄 수 있다
        self.assertIn("유튜브 카드", r.json()["detail"])

    def test_naver_post_url_normalizes_to_blog_root(self):
        self.assertEqual(spine_sources.normalize_naver_blog("https://blog.naver.com/abc_1/223456789"), "https://blog.naver.com/abc_1")


if __name__ == "__main__":
    unittest.main()
