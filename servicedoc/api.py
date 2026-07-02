from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

try:
    from fastapi import FastAPI, BackgroundTasks
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    raise ImportError("fastapi not installed. Install with: pip install servicedoc[api]")

from servicedoc.config import ServiceDocConfig
from servicedoc.main import build_pipeline
from servicedoc.models.repo import RepoConfig

app = FastAPI(title="servicedoc API", version="0.1.0")


class AnalyzeRequest(BaseModel):
    url: str
    branch: str = "main"
    output_dir: str = "./servicedoc_output"
    skip_stages: list[str] = []


class AnalyzeResponse(BaseModel):
    status: str
    output_dir: str
    stages_succeeded: int
    stages_total: int


@app.post("/v1/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    cfg = ServiceDocConfig()
    cfg.output_dir = Path(request.output_dir)
    cfg.skip_stages = request.skip_stages

    pipeline = build_pipeline(cfg)
    repo_config = RepoConfig(url=request.url, branch=request.branch)
    ctx = await pipeline.run(repo_config)

    return AnalyzeResponse(
        status="ok",
        output_dir=str(cfg.output_dir.resolve()),
        stages_succeeded=sum(1 for r in ctx.stage_results if r.success),
        stages_total=len(ctx.stage_results),
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
