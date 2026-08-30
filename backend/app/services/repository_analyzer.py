import os
import base64
import fnmatch

import httpx

GITHUB_API_BASE = "https://api.github.com"

MAX_FILE_SIZE_BYTES = 100 * 1024  # 100 KB

IGNORED_DIRECTORIES = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
}

SENSITIVE_FILE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "credentials.json",
    "secrets.*",
]

LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript (JSX)",
    ".ts": "TypeScript",
    ".tsx": "TypeScript (JSX)",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".cpp": "C++",
    ".h": "C Header",
    ".hpp": "C++ Header",
    ".md": "Markdown",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
}


class GitHubAPIError(Exception):
    """Raised when GitHub's API cannot be reached or returns a failure response."""
    pass


# ---------------------------------------------------------------------------
# Small, single-purpose helper functions
# ---------------------------------------------------------------------------

def _get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def _build_contents_url(owner, repo, path):
    return f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"


def _get_extension(filename):
    return os.path.splitext(filename)[1].lower()


def _is_ignored_directory(name):
    return name in IGNORED_DIRECTORIES


def _is_sensitive_file(filename):
    return any(fnmatch.fnmatch(filename, pattern) for pattern in SENSITIVE_FILE_PATTERNS)


def _is_supported_file(filename):
    return _get_extension(filename) in LANGUAGE_MAP


def _detect_language(filename):
    return LANGUAGE_MAP.get(_get_extension(filename), "Unknown")


# ---------------------------------------------------------------------------
# GitHub API communication
# ---------------------------------------------------------------------------

def _fetch_directory_contents(owner, repo, path, headers):
    """
    Calls GitHub's Contents API for a single path.
    Returns a list of entry dicts (files and directories).
    Raises GitHubAPIError on any failure.
    """
    url = _build_contents_url(owner, repo, path)

    try:
        response = httpx.get(url, headers=headers)
    except httpx.RequestError as exc:
        raise GitHubAPIError(
            "Failed to reach GitHub. Please check your network connection."
        ) from exc

    if response.status_code == 401:
        raise GitHubAPIError(
            "GitHub rejected the request as unauthorized. Check that the token is valid."
        )
    if response.status_code == 403:
        raise GitHubAPIError(
            "GitHub denied access to this repository (forbidden or rate-limited)."
        )
    if response.status_code == 404:
        raise GitHubAPIError(
            f"Repository or path was not found: {owner}/{repo}/{path}"
        )
    if response.status_code != 200:
        raise GitHubAPIError(
            f"GitHub returned an unexpected status code: {response.status_code}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub returned a malformed response.") from exc

    if not isinstance(data, list):
        raise GitHubAPIError(
            f"Expected a directory listing at '{path}' but got something else."
        )

    return data


def _fetch_file_content(file_url, headers):
    """
    Fetches a single file's content from GitHub and decodes it as text.
    Raises GitHubAPIError if it can't be fetched or isn't valid text.
    """
    try:
        response = httpx.get(file_url, headers=headers)
    except httpx.RequestError as exc:
        raise GitHubAPIError(
            "Failed to reach GitHub while downloading a file."
        ) from exc

    if response.status_code != 200:
        raise GitHubAPIError(
            f"GitHub returned status {response.status_code} while downloading a file."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise GitHubAPIError("GitHub returned a malformed file response.") from exc

    encoding = data.get("encoding")
    encoded_content = data.get("content", "")

    if encoding != "base64":
        raise GitHubAPIError("Unexpected file encoding returned by GitHub.")

    try:
        decoded_bytes = base64.b64decode(encoded_content)
        return decoded_bytes.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise GitHubAPIError(
            "File content could not be decoded as text (likely binary)."
        ) from exc


# ---------------------------------------------------------------------------
# Traversal and filtering
# ---------------------------------------------------------------------------

def _discover_files(owner, repo, path, headers):
    """
    Recursively walks the repository starting at `path`.
    Returns a flat list of file entries (dicts), skipping ignored directories.
    """
    entries = _fetch_directory_contents(owner, repo, path, headers)

    discovered = []

    for entry in entries:
        entry_type = entry.get("type")

        if entry_type == "dir":
            if _is_ignored_directory(entry["name"]):
                continue
            discovered.extend(_discover_files(owner, repo, entry["path"], headers))

        elif entry_type == "file":
            discovered.append(entry)

        # Anything else (symlink, submodule) is intentionally ignored.

    return discovered


def _classify_file(entry):
    """
    Decides whether a discovered file should be analyzed.
    Returns (should_analyze: bool, skip_reason: str or None).
    """
    filename = entry["name"]

    if _is_sensitive_file(filename):
        return False, "sensitive file"

    if not _is_supported_file(filename):
        return False, "unsupported file type"

    if entry.get("size", 0) > MAX_FILE_SIZE_BYTES:
        return False, "exceeds maximum file size (100 KB)"

    return True, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_repository(owner, repo, token):
    """
    Discovers, filters, and reads the contents of a GitHub repository's
    source and documentation files.

    Never raises — always returns a dict describing success or failure.
    """
    if not token:
        return {
            "success": False,
            "error": "GitHub token was not provided.",
        }

    headers = _get_headers(token)

    try:
        discovered_files = _discover_files(owner, repo, "", headers)
    except GitHubAPIError as exc:
        return {
            "success": False,
            "error": str(exc),
        }

    analyzed_files = []
    skipped_files = []

    for entry in discovered_files:
        should_analyze, skip_reason = _classify_file(entry)

        if not should_analyze:
            skipped_files.append({"path": entry["path"], "reason": skip_reason})
            continue

        try:
            content = _fetch_file_content(entry["url"], headers)
        except GitHubAPIError as exc:
            skipped_files.append({"path": entry["path"], "reason": str(exc)})
            continue

        analyzed_files.append({
            "path": entry["path"],
            "language": _detect_language(entry["name"]),
            "size": entry.get("size", 0),
            "content": content,
        })

    return {
        "success": True,
        "repository": f"{owner}/{repo}",
        "total_files_discovered": len(discovered_files),
        "total_files_analyzed": len(analyzed_files),
        "total_files_skipped": len(skipped_files),
        "skipped_files": skipped_files,
        "files": analyzed_files,
    }