"""Fixtures for the Calm provider tests: a provider with a mocked MA core and Calm API."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from music_assistant.providers.calm import SUPPORTED_FEATURES, CalmProvider

PROGRAM_ID = "prog1"
GUIDE_ID = "guide1"

# trimmed-down shapes of real Calm API responses
PROGRAM: dict[str, Any] = {
    "id": PROGRAM_ID,
    "title": "Rain Sounds",
    "description": "Gentle rain.",
    "content_type": "Playlist",
    "narrator": {
        "id": "narr1",
        "name": "Curated by Calm",
        "headshot": {"url": "https://assets.calm.com/head.png"},
    },
    "cell_image": {"url": "https://assets.calm.com/cell.jpeg"},
    "guides": [
        {
            "id": "guide2",
            "title": "Second",
            "position": 2,
            "is_free": False,
            "assets": [
                {"url": "https://assets.calm.com/b.wav", "content_type": "audio/wav", "duration": 60}
            ],
        },
        {
            "id": GUIDE_ID,
            "title": "First",
            "position": 1,
            "is_free": False,
            "assets": [
                {"url": "https://assets.calm.com/a.wav", "content_type": "audio/wav", "duration": 1423},
                {"url": "https://assets.calm.com/a.m4a", "content_type": "audio/mp4", "duration": 1423},
            ],
        },
    ],
}

FEED_GUIDE = {
    "type": "guide",
    "guide_id": GUIDE_ID,
    "program_id": PROGRAM_ID,
    "title": "First",
    "subtitle": "Rain Sounds",
    "narrator_name": "Curated by Calm",
    "is_unlocked": True,
    "image": {"url": "https://assets.calm.com/item.jpeg"},
    "assets": [{"url": "https://assets.calm.com/a.oga", "content_type": "audio/ogg", "duration": 2176.6}],
}
FEED_PROGRAM = {
    "type": "program",
    "program_id": PROGRAM_ID,
    "title": "Rain Sounds",
    "narrator_name": "Curated by Calm",
    "is_unlocked": False,
}

FEED_SLEEP = {
    "feed": {
        "id": "sleep",
        "tags": [{"feed_id": "sleep-music", "title": "Music"}, {"pack_class": "tagged-x", "title": "Meditations"}],
        "packs": [
            {"title": None, "pack_class": "upsell", "items": [{"type": "url", "title": "Buy"}]},
            {"title": "Featured", "pack_class": "sleep-featured", "items": [FEED_GUIDE]},
            {"title": "Recently Played", "pack_class": "recent", "items": []},
        ],
    }
}


class FakeCalmApi:
    """Routes provider API calls to canned responses and records them."""

    def __init__(self, unlocked: bool = True) -> None:
        self.calls: list[str] = []
        self.unlocked = unlocked

    async def __call__(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.calls.append(endpoint)
        if endpoint == f"content/programs/{PROGRAM_ID}":
            return {"program": PROGRAM}
        if endpoint.startswith("programs/guides/"):
            return {"id": PROGRAM_ID, "program_id": PROGRAM_ID, "unlocked": self.unlocked, "free": False}
        if endpoint == "packs/feeds/sleep":
            return FEED_SLEEP
        if endpoint == "packs/feeds/home":
            return FEED_SLEEP
        if endpoint == "packs/class/sleep-featured":
            return {"pack": {"items": [FEED_GUIDE, FEED_PROGRAM, {"type": "pack", "pack_class": "sub", "title": "Sub"}]}}
        if endpoint == "packs/class/faves-hydrated":
            return {"pack": {"items": [FEED_GUIDE, FEED_PROGRAM]}}
        if endpoint == "search/v2":
            return {"pack": {"items": [FEED_PROGRAM, FEED_GUIDE]}}
        raise AssertionError(f"unexpected endpoint {endpoint}")


@pytest.fixture
def api() -> FakeCalmApi:
    """Return the fake Calm API."""
    return FakeCalmApi()


@pytest.fixture
def provider(api: FakeCalmApi) -> CalmProvider:
    """Create a CalmProvider with a mocked MA core (no caching) and fake Calm API."""
    mass = Mock()
    # always a cache miss, so every call reaches the (fake) API
    mass.cache.get_with_freshness = AsyncMock(return_value=(None, False, False))
    mass.cache.set = AsyncMock()
    # use_cache runs fetches through mass.create_task
    mass.create_task.side_effect = lambda coro, **_kwargs: asyncio.ensure_future(coro)
    manifest = Mock()
    manifest.domain = "calm"
    config = Mock()
    config.instance_id = "calm--test"
    config.name = "Calm"
    config.enabled = True
    config.get_value.side_effect = lambda key, default=None: {"log_level": "GLOBAL"}.get(key, default)
    prov = CalmProvider(mass, manifest, config, SUPPORTED_FEATURES)
    prov._api = api  # type: ignore[method-assign]
    return prov
