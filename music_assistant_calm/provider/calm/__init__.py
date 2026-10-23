"""
Calm music provider for Music Assistant.

Exposes the Calm catalog (sleep stories, meditations, soundscapes, music) through the
unofficial calm-client library:

- a Calm *program* (album, course, series, playlist) maps to an Album,
- a Calm *guide* (single session/story/track) maps to a Track,
- a narrator or composer maps to an Artist,
- Calm feeds and packs are exposed as browse folders.

Playback requires a Calm login; the provider only streams items Calm reports as
unlocked for the logged-in account.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import TYPE_CHECKING, Any

from music_assistant_models.enums import (
    AlbumType,
    ContentType,
    ImageType,
    MediaType,
    ProviderFeature,
    StreamType,
)
from music_assistant_models.errors import LoginFailed, MediaNotFoundError
from music_assistant_models.media_items import (
    Album,
    Artist,
    AudioFormat,
    BrowseFolder,
    ItemMapping,
    MediaItemImage,
    MediaItemType,
    ProviderMapping,
    RecommendationFolder,
    SearchResults,
    Track,
    UniqueList,
)
from music_assistant_models.streamdetails import StreamDetails

from music_assistant.constants import (
    CONF_ENTRY_UNOFFICIAL_PROVIDER,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from music_assistant.controllers.cache import use_cache
from music_assistant.models.music_provider import MusicProvider

if TYPE_CHECKING:
    from music_assistant_models.config_entries import ConfigEntry, ProviderConfig
    from music_assistant_models.provider import ProviderManifest

    from music_assistant.mass import MusicAssistant
    from music_assistant.models import ProviderInstanceType

    from calm_client import CalmClient

SUPPORTED_FEATURES = {
    ProviderFeature.BROWSE,
    ProviderFeature.SEARCH,
    ProviderFeature.LIBRARY_ALBUMS,
    ProviderFeature.LIBRARY_TRACKS,
    ProviderFeature.RECOMMENDATIONS,
}

# setup_data key holding the (encrypted) token set returned by Calm's login
CONF_CREDENTIALS = "credentials"

# top-level Calm feeds shown when browsing the provider: (feed slug, display name)
ROOT_FEEDS: tuple[tuple[str, str], ...] = (
    ("sleep", "Sleep"),
    ("meditate", "Meditate"),
    ("music", "Music"),
    ("work", "For Work"),
    ("wisdom", "Wisdom"),
    ("kids", "Kids"),
    ("movement", "Movement"),
)

# feed/pack item types that map to playable or browsable MA items; the rest
# (promos, links, breathing bubbles, check-ins) has no audio
GUIDE_TYPE = "guide"
PROGRAM_TYPE = "program"
FOLDER_TYPES = {"pack", "feed"}

CACHE_TTL_CATALOG = 3600 * 24
CACHE_TTL_FEED = 3600 * 3


async def setup(
    mass: MusicAssistant, manifest: ProviderManifest, config: ProviderConfig
) -> ProviderInstanceType:
    """Initialize provider(instance) with given configuration."""
    return CalmProvider(mass, manifest, config, SUPPORTED_FEATURES)


class CalmProvider(MusicProvider):
    """Music provider for the Calm catalog."""

    _client: CalmClient

    async def get_config_entries(self) -> tuple[ConfigEntry, ...]:
        """Return config entries for this provider (credentials come from the setup flow)."""
        return (CONF_ENTRY_UNOFFICIAL_PROVIDER,)

    async def handle_async_init(self) -> None:
        """Log in to Calm, reusing stored tokens where possible."""
        from calm_client import CalmAuthError, CalmClient, Credentials  # noqa: PLC0415

        stored = self.get_setup_value(CONF_CREDENTIALS)
        if isinstance(stored, str) and stored:
            try:
                self._client = CalmClient(Credentials.model_validate_json(stored))
                # cheap authenticated call; also triggers a token refresh when expired
                await self._client.get_favorites()
                self._store_credentials()
                return
            except CalmAuthError:
                self.logger.info("Stored Calm session is no longer valid, logging in again")
                await self._client.close()
            except Exception as err:
                # never block startup on the probe itself; fall back to a fresh login
                self.logger.debug("Could not verify stored Calm session: %s", err)
                await self._client.close()
        await self._login()

    async def unload(self, is_removed: bool = False) -> None:
        """Close the HTTP client on unload."""
        if client := getattr(self, "_client", None):
            await client.close()
        await super().unload(is_removed)

    async def _login(self) -> None:
        """Log in with the configured email and password."""
        from calm_client import CalmAuthError, CalmClient  # noqa: PLC0415

        username = self.get_setup_value(CONF_USERNAME)
        password = self.get_setup_value(CONF_PASSWORD)
        if not username or not password:
            raise LoginFailed("Calm email and password are required")
        self._client = CalmClient()
        try:
            await self._client.login(str(username), str(password))
        except CalmAuthError as err:
            await self._client.close()
            raise LoginFailed(f"Calm login failed: {err}") from err
        self._store_credentials()

    def _store_credentials(self) -> None:
        """Persist the current token set (Calm rotates refresh tokens)."""
        creds = self._client.credentials.model_dump_json(by_alias=True)
        if creds != self.get_setup_value(CONF_CREDENTIALS):
            self._update_setup_data(CONF_CREDENTIALS, creds)

    async def _api(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Call the Calm API, logging in again once if the session expired."""
        from calm_client import CalmAuthError  # noqa: PLC0415

        try:
            result = await self._client._request(method, endpoint, **kwargs)
        except CalmAuthError:
            await self._client.close()
            await self._login()
            result = await self._client._request(method, endpoint, **kwargs)
        # the request may have refreshed (and rotated) the tokens
        self._store_credentials()
        return result

    # ------------------------------------------------------------------
    # Catalog lookups
    # ------------------------------------------------------------------

    @use_cache(CACHE_TTL_CATALOG)
    async def _get_program_data(self, program_id: str) -> dict[str, Any]:
        """Return the raw program (with guides and their assets)."""
        data = await self._api("GET", f"content/programs/{program_id}")
        if not isinstance(data, dict) or "program" not in data:
            raise MediaNotFoundError(f"Calm program {program_id} not found")
        return dict(data["program"])

    @use_cache(CACHE_TTL_FEED)
    async def _get_guide_summary(self, guide_id: str) -> dict[str, Any]:
        """
        Return Calm's per-guide summary: its program id plus the account's lock flags.

        Cached for a shorter time than the catalog, as the lock flags follow the
        account's subscription state.
        """
        data = await self._api("GET", f"programs/guides/{guide_id}")
        if not isinstance(data, dict) or not (data.get("program_id") or data.get("id")):
            raise MediaNotFoundError(f"Calm guide {guide_id} not found")
        return dict(data)

    async def _get_guide_data(self, guide_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Return (guide, program) raw data for a guide id.

        The program detail endpoint carries the audio assets but no lock flags, so the
        flags from the guide summary are copied onto the returned program.
        """
        summary = await self._get_guide_summary(guide_id)
        program = dict(await self._get_program_data(str(summary.get("program_id") or summary["id"])))
        for key in ("unlocked", "free"):
            if key in summary:
                program[key] = summary[key]
        for guide in program.get("guides", []):
            if guide.get("id") == guide_id:
                return guide, program
        raise MediaNotFoundError(f"Calm guide {guide_id} not found in its program")

    @use_cache(CACHE_TTL_FEED)
    async def _get_feed(self, feed_id: str) -> dict[str, Any]:
        """Return a raw feed (a list of packs)."""
        data = await self._api("GET", f"packs/feeds/{feed_id}")
        return dict(data.get("feed", data))

    @use_cache(CACHE_TTL_FEED)
    async def _get_pack(self, pack_class: str) -> dict[str, Any]:
        """Return a raw pack with all of its items."""
        data = await self._api("GET", f"packs/class/{pack_class}")
        return dict(data.get("pack", data))

    # ------------------------------------------------------------------
    # MusicProvider API
    # ------------------------------------------------------------------

    async def get_album(self, prov_album_id: str) -> Album:
        """Get a Calm program as an album."""
        return self._parse_program(await self._get_program_data(prov_album_id))

    async def get_album_tracks(self, prov_album_id: str) -> list[Track]:
        """Get the guides of a Calm program as album tracks."""
        program = await self._get_program_data(prov_album_id)
        album = self._parse_program(program)
        return [
            self._parse_guide(guide, program=program, album=album)
            for guide in sorted(program.get("guides", []), key=lambda g: g.get("position") or 0)
            if guide.get("id")
        ]

    async def get_track(self, prov_track_id: str) -> Track:
        """Get a single Calm guide as a track."""
        guide, program = await self._get_guide_data(prov_track_id)
        return self._parse_guide(guide, program=program, album=self._parse_program(program))

    async def get_artist(self, prov_artist_id: str) -> Artist:
        """Get a narrator/composer as an artist (Calm exposes no standalone artist lookup)."""
        return self._parse_artist(prov_artist_id, prov_artist_id)

    async def get_library_albums(self) -> AsyncGenerator[Album]:
        """Yield the programs in the user's Calm favorites."""
        for item in await self._get_favorite_items():
            if item.get("type") == PROGRAM_TYPE and item.get("program_id"):
                yield self._parse_feed_program(item)

    async def get_library_tracks(self) -> AsyncGenerator[Track]:
        """Yield the guides in the user's Calm favorites."""
        for item in await self._get_favorite_items():
            if item.get("type") == GUIDE_TYPE and item.get("guide_id"):
                yield self._parse_feed_guide(item)

    async def _get_favorite_items(self) -> list[dict[str, Any]]:
        """Return the raw favorite items (empty when Calm returns no favorites pack)."""
        data = await self._api("GET", "packs/class/faves-hydrated")
        return list(data.get("pack", {}).get("items", [])) if isinstance(data, dict) else []

    async def search(
        self,
        search_query: str,
        media_types: list[MediaType],
        limit: int = 5,
    ) -> SearchResults:
        """Search the Calm catalog."""
        result = SearchResults()
        data = await self._api("GET", "search/v2", params={"query": search_query})
        items = data.get("pack", data).get("items", []) if isinstance(data, dict) else []
        albums: list[Album] = []
        tracks: list[Track] = []
        for item in items:
            item_type = item.get("type")
            if item_type == PROGRAM_TYPE and item.get("program_id"):
                albums.append(self._parse_feed_program(item))
            elif item_type == GUIDE_TYPE and item.get("guide_id"):
                tracks.append(self._parse_feed_guide(item))
        if MediaType.ALBUM in media_types:
            result.albums = albums[:limit]
        if MediaType.TRACK in media_types:
            result.tracks = tracks[:limit]
        return result

    async def browse(self, path: str) -> Sequence[MediaItemType | ItemMapping | BrowseFolder]:
        """
        Browse Calm feeds and packs.

        Paths: ``calm://`` (root feeds), ``calm://feed/<feed_id>`` (packs of a feed)
        and ``calm://pack/<pack_class>`` (items of a pack).
        """
        subpath = path.split("://", 1)[1] if "://" in path else ""
        kind, _, ident = subpath.partition("/")
        if not kind:
            return [self._folder(path, f"feed/{feed_id}", name) for feed_id, name in ROOT_FEEDS]
        if kind == "feed" and ident:
            return self._browse_feed(path, await self._get_feed(ident))
        if kind == "pack" and ident:
            return self._parse_pack_items((await self._get_pack(ident)).get("items", []), path)
        return await super().browse(path)

    def _browse_feed(
        self, path: str, feed: dict[str, Any]
    ) -> list[MediaItemType | ItemMapping | BrowseFolder]:
        """List a feed's packs (that hold playable content) and its tag sub-feeds."""
        root = path.split("://", 1)[0] + "://"
        result: list[MediaItemType | ItemMapping | BrowseFolder] = []
        for pack in feed.get("packs", []):
            pack_class = pack.get("pack_class")
            items = pack.get("items", [])
            if not pack_class or not pack.get("title"):
                continue
            # skip promo banners and empty personal rows (e.g. recently played for a new user)
            if not items or not any(i.get("type") in {GUIDE_TYPE, PROGRAM_TYPE} for i in items):
                continue
            result.append(self._folder(root, f"pack/{pack_class}", pack["title"]))
        for tag in feed.get("tags", []):
            if tag.get("feed_id") and tag.get("title"):
                result.append(self._folder(root, f"feed/{tag['feed_id']}", tag["title"]))
            elif tag.get("pack_class") and tag.get("title"):
                result.append(self._folder(root, f"pack/{tag['pack_class']}", tag["title"]))
        return result

    def _parse_pack_items(
        self, items: list[dict[str, Any]], path: str
    ) -> list[MediaItemType | ItemMapping | BrowseFolder]:
        """Map the items of a pack to tracks, albums and sub-folders."""
        root = path.split("://", 1)[0] + "://"
        result: list[MediaItemType | ItemMapping | BrowseFolder] = []
        for item in items:
            item_type = item.get("type")
            if item_type == GUIDE_TYPE and item.get("guide_id"):
                result.append(self._parse_feed_guide(item))
            elif item_type == PROGRAM_TYPE and item.get("program_id"):
                result.append(self._parse_feed_program(item))
            elif item_type == "pack" and item.get("pack_class"):
                result.append(self._folder(root, f"pack/{item['pack_class']}", item.get("title")))
            elif item_type == "feed" and item.get("feed_id"):
                result.append(self._folder(root, f"feed/{item['feed_id']}", item.get("title")))
        return result

    async def get_recommendations(self) -> list[RecommendationFolder]:
        """Expose the packs of Calm's home feed as recommendation rows."""
        feed = await self._get_feed("home")
        rows: list[RecommendationFolder] = []
        for pack in feed.get("packs", []):
            items = pack.get("items", [])
            if not pack.get("pack_class") or not pack.get("title"):
                continue
            if not any(i.get("type") in {GUIDE_TYPE, PROGRAM_TYPE} for i in items):
                continue
            rows.append(
                RecommendationFolder(
                    item_id=f"pack/{pack['pack_class']}",
                    provider=self.instance_id,
                    name=pack["title"],
                )
            )
        return rows

    async def get_recommendation_items(
        self, item_id: str
    ) -> UniqueList[MediaItemType | ItemMapping | BrowseFolder]:
        """Return the items of a recommendation row (a Calm pack)."""
        pack_class = item_id.removeprefix("pack/")
        items = (await self._get_pack(pack_class)).get("items", [])
        return UniqueList(self._parse_pack_items(items, f"{self.instance_id}://"))

    async def get_stream_details(self, item_id: str, media_type: MediaType) -> StreamDetails:
        """Return the stream details for a guide."""
        guide, program = await self._get_guide_data(item_id)
        if not self._is_available(guide, program):
            raise MediaNotFoundError(f"Calm guide {item_id} is locked for this account")
        asset = self._pick_asset(guide.get("assets", []))
        if not asset:
            raise MediaNotFoundError(f"Calm guide {item_id} has no audio")
        duration = asset.get("duration")
        return StreamDetails(
            provider=self.instance_id,
            item_id=item_id,
            audio_format=AudioFormat(content_type=self._content_type(asset)),
            media_type=MediaType.TRACK,
            stream_type=StreamType.HTTP,
            path=asset["url"],
            duration=int(duration) if duration else None,
            allow_seek=True,
            can_seek=True,
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _folder(self, root: str, subpath: str, name: str | None) -> BrowseFolder:
        """Build a browse folder below this provider."""
        root = root if root.endswith("://") else root.split("://", 1)[0] + "://"
        return BrowseFolder(
            item_id=subpath,
            provider=self.instance_id,
            path=f"{root}{subpath}",
            name=name or subpath,
        )

    def _mapping(self, item_id: str, available: bool = True, **kwargs: Any) -> ProviderMapping:
        return ProviderMapping(
            item_id=item_id,
            provider_domain=self.domain,
            provider_instance=self.instance_id,
            available=available,
            **kwargs,
        )

    def _image(self, url: str | None) -> MediaItemImage | None:
        if not url:
            return None
        return MediaItemImage(
            type=ImageType.THUMB,
            path=url,
            provider=self.instance_id,
            remotely_accessible=True,
        )

    def _parse_artist(self, artist_id: str, name: str, image_url: str | None = None) -> Artist:
        artist = Artist(
            item_id=artist_id,
            provider=self.instance_id,
            name=name,
            provider_mappings={self._mapping(artist_id)},
        )
        if image := self._image(image_url):
            artist.metadata.add_image(image)
        return artist

    def _program_artist(self, program: dict[str, Any]) -> Artist | None:
        """Return the narrator/composer of a raw program, if known."""
        narrator = program.get("narrator")
        if isinstance(narrator, dict) and narrator.get("name"):
            headshot = (narrator.get("headshot") or {}).get("url")
            return self._parse_artist(
                str(narrator.get("id") or narrator["name"]), narrator["name"], headshot
            )
        if isinstance(narrator, str) and narrator:
            return self._parse_artist(str(program.get("narrator_id") or narrator), narrator)
        return None

    @staticmethod
    def _program_image(program: dict[str, Any]) -> str | None:
        for key in ("cell_image", "untitled_cell_image", "image", "background_image"):
            if isinstance(program.get(key), dict) and program[key].get("url"):
                return str(program[key]["url"])
        return None

    @staticmethod
    def _is_available(item: dict[str, Any], program: dict[str, Any] | None = None) -> bool:
        """Return whether Calm reports the item as playable for the logged-in account."""
        for source in (item, program or {}):
            for key in ("is_unlocked", "unlocked", "is_free", "free"):
                if source.get(key) is True:
                    return True
        # program detail responses omit the lock flags; treat unknown as available
        return not any(
            key in source
            for source in (item, program or {})
            for key in ("is_unlocked", "unlocked")
        )

    @staticmethod
    def _pick_asset(assets: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Prefer compressed audio over wav to save bandwidth; ignore video."""
        audio = [a for a in assets if a.get("url") and str(a.get("content_type", "")).startswith("audio/")]
        order = {"audio/mp4": 0, "audio/mpeg": 1, "audio/ogg": 2, "audio/wav": 3}
        audio.sort(key=lambda a: order.get(a.get("content_type", ""), 9))
        return audio[0] if audio else None

    @staticmethod
    def _content_type(asset: dict[str, Any]) -> ContentType:
        """Map an asset's mime type (or file extension) to an MA content type."""
        mime = str(asset.get("content_type", ""))
        content_type = ContentType.try_parse(mime) if "/" in mime else ContentType.UNKNOWN
        if content_type == ContentType.UNKNOWN:
            content_type = ContentType.try_parse(str(asset.get("url", "")))
        return content_type

    def _parse_program(self, program: dict[str, Any]) -> Album:
        """Parse a full program (content/programs response) to an Album."""
        program_id = str(program["id"])
        guides = program.get("guides", [])
        album = Album(
            item_id=program_id,
            provider=self.instance_id,
            name=program.get("title") or program_id,
            album_type=AlbumType.SINGLE if len(guides) == 1 else AlbumType.ALBUM,
            provider_mappings={self._mapping(program_id, self._is_available(program))},
        )
        if artist := self._program_artist(program):
            album.artists.append(artist)
        if image := self._image(self._program_image(program)):
            album.metadata.add_image(image)
        if program.get("description"):
            album.metadata.description = program["description"]
        return album

    def _parse_guide(self, guide: dict[str, Any], program: dict[str, Any], album: Album) -> Track:
        """Parse a guide from a full program to a Track."""
        guide_id = str(guide["id"])
        asset = self._pick_asset(guide.get("assets", []))
        track = Track(
            item_id=guide_id,
            provider=self.instance_id,
            name=guide.get("title") or album.name,
            duration=int(asset["duration"]) if asset and asset.get("duration") else 0,
            track_number=guide.get("position") or 0,
            album=album,
            provider_mappings={
                self._mapping(
                    guide_id,
                    bool(asset) and self._is_available(guide, program),
                    audio_format=AudioFormat(
                        content_type=self._content_type(asset) if asset else ContentType.UNKNOWN
                    ),
                )
            },
        )
        if guide.get("narrator_name"):
            track.artists.append(
                self._parse_artist(
                    str(guide.get("narrator_id") or guide["narrator_name"]), guide["narrator_name"]
                )
            )
        elif album.artists:
            track.artists = album.artists
        if image := self._image(self._program_image(program)):
            track.metadata.add_image(image)
        return track

    def _parse_feed_program(self, item: dict[str, Any]) -> Album:
        """Parse a program entry from a feed, pack or search result to an Album."""
        program_id = str(item["program_id"])
        album = Album(
            item_id=program_id,
            provider=self.instance_id,
            name=item.get("title") or program_id,
            provider_mappings={self._mapping(program_id, self._is_available(item))},
        )
        if item.get("narrator_name"):
            album.artists.append(self._parse_artist(item["narrator_name"], item["narrator_name"]))
        if image := self._image((item.get("image") or {}).get("url")):
            album.metadata.add_image(image)
        if item.get("subtitle"):
            album.metadata.description = item["subtitle"]
        return album

    def _parse_feed_guide(self, item: dict[str, Any]) -> Track:
        """Parse a guide entry from a feed, pack or search result to a Track."""
        guide_id = str(item["guide_id"])
        asset = self._pick_asset(item.get("assets", []))
        track = Track(
            item_id=guide_id,
            provider=self.instance_id,
            name=item.get("title") or guide_id,
            duration=int(asset["duration"]) if asset and asset.get("duration") else 0,
            provider_mappings={
                self._mapping(
                    guide_id,
                    self._is_available(item),
                    audio_format=AudioFormat(
                        content_type=self._content_type(asset) if asset else ContentType.UNKNOWN
                    ),
                )
            },
        )
        if item.get("program_id"):
            track.album = ItemMapping(
                item_id=str(item["program_id"]),
                provider=self.instance_id,
                name=item.get("subtitle") or item.get("title") or "",
                media_type=MediaType.ALBUM,
            )
        if item.get("narrator_name"):
            track.artists.append(self._parse_artist(item["narrator_name"], item["narrator_name"]))
        if image := self._image((item.get("image") or {}).get("url")):
            track.metadata.add_image(image)
        return track
