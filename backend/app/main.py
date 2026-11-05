import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from app.cache import TTLCache

from app.coc_client import (
    ForbiddenError,
    InvalidTagError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    get_clan,
    get_player,
    get_war,
    get_regular_war,
    get_league_wars,
    get_clan_members,
    get_clan_activity_report,
    get_clan_raids,
    get_clan_games,
    get_player_activity,
    get_next_war_analysis,
    normalize_tag,
    encode_tag,
)
from app.settings import settings, validate_settings
from app.war_history import WarHistory

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


async def collect_war_history(
    client: httpx.AsyncClient, cache: TTLCache, history: WarHistory
) -> None:
    """Periodically save regular and CWL wars, including completed CWL rounds."""
    while True:
        try:
            regular = await get_regular_war(client, cache)
            if history.save(regular):
                logger.info("Saved regular clan war snapshot")
            _, cwl_wars = await get_league_wars(client, cache)
            for war in cwl_wars:
                history.save(war)
            if cwl_wars:
                logger.info("Reviewed %s CWL wars", len(cwl_wars))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("War snapshot collection failed; will retry")
        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    missing = validate_settings()
    if missing:
        logger.error("Missing required environment variables: %s", ", ".join(missing))
        raise SystemExit(1)
    logger.info("Environment validation passed")

    redis = TTLCache()
    timeout = httpx.Timeout(settings.request_timeout_seconds)
    headers = {"Authorization": "Bearer " + str(settings.coc_token)}
    client = httpx.AsyncClient(headers=headers, timeout=timeout)

    app.state.redis = redis
    app.state.http_client = client
    history_path = os.environ.get("WAR_HISTORY_DB_PATH", "/data/war_history.db")
    app.state.history = WarHistory(history_path)
    poller = asyncio.create_task(
        collect_war_history(client, redis, app.state.history),
        name="war-history-poller",
    )
    logger.info("Backend startup complete; war history DB=%s", history_path)
    try:
        yield
    finally:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        await client.aclose()
        await redis.close()
        logger.info("Backend shutdown complete")


app = FastAPI(lifespan=lifespan)


def get_redis(request: Request) -> TTLCache:
    return request.app.state.redis


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


@app.get("/clan")
async def clan(request: Request):
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_clan(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/player/{tag}")
async def player(tag: str, request: Request):
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_player(client, redis, tag)
    except InvalidTagError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/war")
async def war(request: Request):
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_war(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/top-players")
async def top_players(request: Request, limit: int = 10):
    """Get top clan members by trophies."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_clan_members(client, redis, limit=min(limit, 50))
    except InvalidTagError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/activity-report")
async def activity_report(request: Request):
    """Get clan activity report."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_clan_activity_report(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/raids")
async def raids(request: Request):
    """Get clan raids (capital games) information."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_clan_raids(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/games")
async def games(request: Request):
    """Get clan games (Clan Games) information."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_clan_games(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/activity")
async def activity(request: Request):
    """Get clan members activity statistics."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_player_activity(client, redis)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/next-war")
async def next_war(request: Request):
    """Analyze and recommend lineup for next war."""
    redis = get_redis(request)
    client = get_http_client(request)
    try:
        return await get_next_war_analysis(client, redis, request.app.state.history)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnauthorizedError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ForbiddenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

class PlayerVerificationRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


@app.post("/verify-player/{tag}")
async def verify_player(tag: str, body: PlayerVerificationRequest, request: Request):
    """Verify the in-game player API token without logging or retaining it."""
    try:
        player_tag = normalize_tag(tag)
    except InvalidTagError as exc:
        raise HTTPException(status_code=400, detail="Invalid tag") from exc
    client = get_http_client(request)
    url = f"{settings.coc_api_base}/players/{encode_tag(player_tag)}/verifytoken"
    try:
        response = await client.post(url, json={"token": body.token})
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="CoC verification timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="CoC verification unavailable") from exc
    if response.status_code in (401, 403, 429):
        raise HTTPException(status_code=response.status_code, detail="CoC rejected verification request")
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="CoC verification error")
    return {"verified": response.json().get("status") == "ok"}
