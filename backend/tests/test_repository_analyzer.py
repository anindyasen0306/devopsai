from unittest.mock import patch

import httpx
import pytest

from app.services.repository_analyzer import (
    GitHubAPIError,
    MAX_FILE_SIZE_BYTES,
    _classify_file,
    _detect_language,
    _discover_files,
    _fetch_directory_contents,
    _fetch_file_content,
    _is_ignored_directory,
    _is_sensitive_file,
    _is_supported_file,
    analyze_repository,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class FakeResponse:
    """A minimal stand-in for an httpx.Response, used for mocking."""

    def __init__(self, status_code, json_data=None, json_raises=False):
        self.status_code = status_code
        self._json_data = json_data
        self._json_raises = json_raises

    def json(self):
        if self._json_raises:
            raise ValueError("invalid JSON")
        return self._json_data


def make_file_entry(name, path, size=100, url="https://api.github.com/fake"):
    return {"name": name, "path": path, "type": "file", "size": size, "url": url}


def make_dir_entry(name, path):
    return {"name": name, "path": path, "type": "dir"}


# ---------------------------------------------------------------------------
# 1. Language detection (pure function)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename,expected_language", [
    ("main.py", "Python"),
    ("app.js", "JavaScript"),
    ("App.jsx", "JavaScript (JSX)"),
    ("index.ts", "TypeScript"),
    ("Component.tsx", "TypeScript (JSX)"),
    ("Main.java", "Java"),
    ("server.go", "Go"),
    ("lib.rs", "Rust"),
    ("README.md", "Markdown"),
])
def test_detect_language(filename, expected_language):
    assert _detect_language(filename) == expected_language


# ---------------------------------------------------------------------------
# 2. File filtering by extension (pure function)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", ["main.py", "App.jsx", "README.md"])
def test_supported_file_is_accepted(filename):
    assert _is_supported_file(filename) is True


@pytest.mark.parametrize("filename", ["image.png", "video.mp4", "archive.zip"])
def test_unsupported_file_is_rejected(filename):
    assert _is_supported_file(filename) is False


# ---------------------------------------------------------------------------
# 3. Sensitive file filtering (pure function)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", [
    ".env",
    ".env.local",
    ".env.production",
    "private.pem",
    "secret.key",
    "credentials.json",
    "secrets.yaml",
])
def test_sensitive_file_is_rejected(filename):
    # We only assert the boolean result — never print or log the filename's contents.
    assert _is_sensitive_file(filename) is True


def test_normal_file_is_not_flagged_as_sensitive():
    assert _is_sensitive_file("main.py") is False


# ---------------------------------------------------------------------------
# 4. Directory filtering (pure function)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("directory_name", [
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
])
def test_ignored_directory_is_detected(directory_name):
    assert _is_ignored_directory(directory_name) is True


def test_normal_directory_is_not_ignored():
    assert _is_ignored_directory("src") is False


# ---------------------------------------------------------------------------
# 5. File size limit (pure function, via _classify_file)
# ---------------------------------------------------------------------------

def test_small_file_is_accepted():
    entry = make_file_entry("main.py", "main.py", size=MAX_FILE_SIZE_BYTES - 1)
    should_analyze, reason = _classify_file(entry)
    assert should_analyze is True
    assert reason is None


def test_large_file_is_rejected():
    entry = make_file_entry("main.py", "main.py", size=MAX_FILE_SIZE_BYTES + 1)
    should_analyze, reason = _classify_file(entry)
    assert should_analyze is False
    assert "100 KB" in reason


# ---------------------------------------------------------------------------
# 6. File content decoding
# ---------------------------------------------------------------------------

def test_fetch_file_content_decodes_base64():
    import base64

    original_text = "print('hello world')"
    encoded = base64.b64encode(original_text.encode("utf-8")).decode("ascii")
    fake_response = FakeResponse(200, {"encoding": "base64", "content": encoded})

    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        result = _fetch_file_content("https://api.github.com/fake", headers={})

    assert result == original_text


def test_fetch_file_content_rejects_non_utf8_content():
    import base64

    non_utf8_bytes = b"\xff\xfe\x00\x01"
    encoded = base64.b64encode(non_utf8_bytes).decode("ascii")
    fake_response = FakeResponse(200, {"encoding": "base64", "content": encoded})

    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_file_content("https://api.github.com/fake", headers={})


# ---------------------------------------------------------------------------
# 7. GitHub API error handling
# ---------------------------------------------------------------------------

def test_github_401_raises_error():
    fake_response = FakeResponse(401)
    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


def test_github_403_raises_error():
    fake_response = FakeResponse(403)
    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


def test_github_404_raises_error():
    fake_response = FakeResponse(404)
    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


def test_github_unexpected_status_raises_error():
    fake_response = FakeResponse(500)
    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


def test_network_failure_raises_error():
    with patch(
        "app.services.repository_analyzer.httpx.get",
        side_effect=httpx.RequestError("connection failed"),
    ):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


# ---------------------------------------------------------------------------
# 8. Directory API response parsing
# ---------------------------------------------------------------------------

def test_fetch_directory_contents_returns_list():
    entries = [make_file_entry("main.py", "main.py")]
    fake_response = FakeResponse(200, entries)

    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        result = _fetch_directory_contents("owner", "repo", "", headers={})

    assert result == entries


def test_fetch_directory_contents_rejects_non_list_response():
    # Simulates hitting a file path instead of a directory path.
    fake_response = FakeResponse(200, {"name": "main.py", "type": "file"})

    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


def test_fetch_directory_contents_rejects_malformed_json():
    fake_response = FakeResponse(200, json_raises=True)

    with patch("app.services.repository_analyzer.httpx.get", return_value=fake_response):
        with pytest.raises(GitHubAPIError):
            _fetch_directory_contents("owner", "repo", "", headers={})


# ---------------------------------------------------------------------------
# 9. Recursive discovery
# ---------------------------------------------------------------------------

def test_recursive_discovery_finds_files_and_skips_ignored_directories():
    root_entries = [
        make_dir_entry("backend", "backend"),
        make_dir_entry("tests", "tests"),
        make_dir_entry("node_modules", "node_modules"),
    ]
    backend_entries = [
        make_file_entry("main.py", "backend/main.py"),
        make_file_entry("utils.py", "backend/utils.py"),
    ]
    tests_entries = [
        make_file_entry("test_main.py", "tests/test_main.py"),
    ]

    def fake_get(url, headers=None):
        if url.endswith("/contents/"):
            return FakeResponse(200, root_entries)
        if url.endswith("/contents/backend"):
            return FakeResponse(200, backend_entries)
        if url.endswith("/contents/tests"):
            return FakeResponse(200, tests_entries)
        # node_modules must never be requested, since it's an ignored directory.
        raise AssertionError(f"Unexpected directory request: {url}")

    with patch("app.services.repository_analyzer.httpx.get", side_effect=fake_get):
        discovered = _discover_files("owner", "repo", "", headers={})

    discovered_paths = {entry["path"] for entry in discovered}

    assert discovered_paths == {
        "backend/main.py",
        "backend/utils.py",
        "tests/test_main.py",
    }


# ---------------------------------------------------------------------------
# 10. analyze_repository — success case
# ---------------------------------------------------------------------------

def test_analyze_repository_success_returns_expected_structure():
    fake_discovered = [
        make_file_entry("main.py", "main.py", size=100),
    ]

    with patch(
        "app.services.repository_analyzer._discover_files",
        return_value=fake_discovered,
    ), patch(
        "app.services.repository_analyzer._fetch_file_content",
        return_value="print('hello')",
    ):
        result = analyze_repository("owner", "repo", "fake-token")

    assert result["success"] is True
    assert result["repository"] == "owner/repo"
    assert result["total_files_discovered"] == 1
    assert result["total_files_analyzed"] == 1
    assert result["total_files_skipped"] == 0
    assert result["skipped_files"] == []

    analyzed_file = result["files"][0]
    assert analyzed_file["path"] == "main.py"
    assert analyzed_file["language"] == "Python"
    assert analyzed_file["size"] == 100
    assert analyzed_file["content"] == "print('hello')"


# ---------------------------------------------------------------------------
# 11. Missing token
# ---------------------------------------------------------------------------

def test_analyze_repository_missing_token_fails_safely():
    result = analyze_repository("owner", "repo", None)

    assert result["success"] is False
    assert "error" in result
    assert isinstance(result["error"], str)
    assert "token" in result["error"].lower()


# ---------------------------------------------------------------------------
# 12. Secret protection
# ---------------------------------------------------------------------------

def test_analyze_repository_excludes_sensitive_files():
    fake_discovered = [
        make_file_entry(".env", ".env", size=50, url="https://api.github.com/env-file"),
        make_file_entry("main.py", "main.py", size=100, url="https://api.github.com/main-file"),
    ]

    with patch(
        "app.services.repository_analyzer._discover_files",
        return_value=fake_discovered,
    ), patch(
        "app.services.repository_analyzer._fetch_file_content",
        return_value="print('hello')",
    ) as mock_fetch_content:
        result = analyze_repository("owner", "repo", "fake-token")

    analyzed_paths = [f["path"] for f in result["files"]]
    skipped_paths = [s["path"] for s in result["skipped_files"]]

    assert ".env" not in analyzed_paths
    assert ".env" in skipped_paths
    assert "main.py" in analyzed_paths

    # The sensitive file's content should never even be requested —
    # content fetching should only have been called once, for main.py.
    fetched_urls = [call.args[0] for call in mock_fetch_content.call_args_list]
    assert fetched_urls == ["https://api.github.com/main-file"]