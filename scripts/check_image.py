"""Run inside the built add-on image: MA must find and load the Calm provider."""

import asyncio
import os

from music_assistant_models.provider import ProviderManifest

from music_assistant.helpers.util import load_provider_module
from music_assistant.mass import PROVIDERS_PATH


async def main() -> None:
    """Parse the manifest and load the module the same way MA does at startup."""
    assert "calm" in os.listdir(PROVIDERS_PATH), "calm provider missing from image"
    manifest = await ProviderManifest.parse(os.path.join(PROVIDERS_PATH, "calm", "manifest.json"))
    module = await load_provider_module(manifest.domain, manifest.requirements)
    assert hasattr(module, "setup"), "provider module has no setup()"
    print(f"loaded {module.__name__} with requirements {manifest.requirements}")


asyncio.run(main())
