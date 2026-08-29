import os
import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_API_URL = "https://api.github.com/user/repos"


def get_user_repositories():
    """
    Fetches the authenticated user's repositories from GitHub.
    Returns a dict with either "success" data or an "error" message.
    """

    token = os.getenv("GITHUB_TOKEN")

    if not token:
        return {
            "success": False,
            "error": "GITHUB_TOKEN environment variable is not set."
        }

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = httpx.get(GITHUB_API_URL, headers=headers)
    except httpx.RequestError:
        return {
            "success": False,
            "error": "Failed to reach GitHub. Please check your network connection."
        }

    if response.status_code == 401:
        return {
            "success": False,
            "error": "GitHub rejected the request as unauthorized. Check that the token is valid."
        }

    if response.status_code != 200:
        return {
            "success": False,
            "error": f"GitHub returned an unexpected status code: {response.status_code}"
        }

    repositories = response.json()

    simplified_repositories = [
        {
            "id": repo["id"],
            "name": repo["name"],
            "full_name": repo["full_name"],
            "private": repo["private"],
            "html_url": repo["html_url"],
            "default_branch": repo["default_branch"],
        }
        for repo in repositories
    ]

    return {
        "success": True,
        "repositories": simplified_repositories
    }