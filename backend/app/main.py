from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.services.github_service import get_user_repositories


app = FastAPI()


@app.get("/api/health")
def health_check():
    return {
        "status": "ok",
        "service": "devopsai-backend"
    }


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/github/repos")
def get_github_repos():
    result = get_user_repositories()

    if not result["success"]:
        raise HTTPException(
            status_code=502,
            detail=result["error"]
        )

    return result["repositories"]