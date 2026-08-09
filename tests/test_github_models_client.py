import json

from github_models_client import build_chat_completions_url, call_chat_completion, filter_safe_image_urls, is_safe_image_url


def test_build_chat_completions_url():
    assert build_chat_completions_url(
        "https://example.openai.azure.com/",
        "gpt-4o mini",
        "2024-10-21",
    ) == (
        "https://example.openai.azure.com/openai/deployments/gpt-4o%20mini/chat/completions"
        "?api-version=2024-10-21"
    )


def test_call_chat_completion_uses_azure_api_key(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"choices": []}'

    def fake_urlopen(api_request, timeout):
        captured["request"] = api_request
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setattr("github_models_client.request.urlopen", fake_urlopen)

    response = call_chat_completion(
        token="secret",
        api_version="2024-10-21",
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hello"}],
        max_attempts=1,
    )

    api_request = captured["request"]
    assert response == {"choices": []}
    assert api_request.full_url.endswith(
        "/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21"
    )
    assert api_request.headers["Api-key"] == "secret"
    assert "model" not in json.loads(api_request.data)


def test_call_chat_completion_uses_new_token_limit_for_gpt5(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"choices": []}'

    def fake_urlopen(api_request, timeout):
        captured["body"] = json.loads(api_request.data)
        return Response()

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setattr("github_models_client.request.urlopen", fake_urlopen)

    call_chat_completion(
        token="secret",
        api_version="2024-10-21",
        model="gpt-5-4-nano",
        messages=[{"role": "user", "content": "hello"}],
        max_tokens=100,
        max_attempts=1,
    )

    assert captured["body"]["max_completion_tokens"] == 100
    assert "max_tokens" not in captured["body"]


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
