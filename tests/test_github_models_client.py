from github_models_client import filter_safe_image_urls, is_safe_image_url


class TestIsSafeImageUrl:
    def test_https_twimg(self):
        assert is_safe_image_url("https://pbs.twimg.com/media/abc.jpg") is True

    def test_https_subdomain_twimg(self):
        assert is_safe_image_url("https://video.twimg.com/x.mp4") is True

    def test_http_rejected(self):
        assert is_safe_image_url("http://pbs.twimg.com/media/abc.jpg") is False

    def test_other_host_rejected(self):
        assert is_safe_image_url("https://example.com/x.jpg") is False

    def test_internal_ip_rejected(self):
        assert is_safe_image_url("https://127.0.0.1/x.jpg") is False
        assert is_safe_image_url("https://169.254.169.254/latest/meta-data/") is False

    def test_lookalike_rejected(self):
        assert is_safe_image_url("https://twimg.com.evil.com/x.jpg") is False

    def test_blank(self):
        assert is_safe_image_url("") is False
        assert is_safe_image_url("   ") is False


class TestFilterSafeImageUrls:
    def test_filters(self):
        urls = [
            "https://pbs.twimg.com/media/a.jpg",
            "https://example.com/b.jpg",
            "https://video.twimg.com/c.mp4",
            "",
        ]
        assert filter_safe_image_urls(urls) == [
            "https://pbs.twimg.com/media/a.jpg",
            "https://video.twimg.com/c.mp4",
        ]
