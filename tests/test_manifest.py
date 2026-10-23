"""Check the provider manifest and add-on config agree with Music Assistant."""

from __future__ import annotations

import json
from pathlib import Path

from music_assistant_models.provider import ProviderManifest

ADDON_DIR = Path(__file__).parent.parent / "music_assistant_calm"
PROVIDER_DIR = ADDON_DIR / "provider" / "calm"


async def test_manifest_parses() -> None:
    manifest = await ProviderManifest.parse(str(PROVIDER_DIR / "manifest.json"))
    assert manifest.domain == "calm"
    assert manifest.requirements == ["calm-client==0.2.1"]


def test_dockerfile_installs_manifest_requirement() -> None:
    requirement = json.loads((PROVIDER_DIR / "manifest.json").read_text())["requirements"][0]
    version = requirement.split("==", 1)[1]
    assert f"ARG CALM_CLIENT_VERSION={version}" in (ADDON_DIR / "Dockerfile").read_text()


def test_build_image_matches_addon_version() -> None:
    config = (ADDON_DIR / "config.yaml").read_text()
    build = (ADDON_DIR / "build.yaml").read_text()
    version = next(l.split(":", 1)[1].strip() for l in config.splitlines() if l.startswith("version:"))
    upstream = version.split("-calm", 1)[0]
    assert f"ghcr.io/music-assistant/server:{upstream}" in build
    assert f"ghcr.io/music-assistant/server:{upstream}" in (ADDON_DIR / "Dockerfile").read_text()
