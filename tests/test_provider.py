"""Tests for the Calm provider's mapping of Calm content to Music Assistant items."""

from __future__ import annotations

import pytest
from music_assistant_models.enums import AlbumType, ContentType, MediaType, StreamType
from music_assistant_models.errors import MediaNotFoundError
from music_assistant_models.media_items import Album, BrowseFolder, Track

from music_assistant.providers.calm import CalmProvider

from .conftest import GUIDE_ID, PROGRAM_ID, FakeCalmApi


async def test_get_album_maps_program(provider: CalmProvider) -> None:
    album = await provider.get_album(PROGRAM_ID)
    assert album.name == "Rain Sounds"
    assert album.album_type == AlbumType.ALBUM
    assert [a.name for a in album.artists] == ["Curated by Calm"]
    assert album.metadata.description == "Gentle rain."
    assert album.metadata.images and album.metadata.images[0].path.endswith("cell.jpeg")


async def test_album_tracks_ordered_by_position(provider: CalmProvider) -> None:
    tracks = await provider.get_album_tracks(PROGRAM_ID)
    assert [t.item_id for t in tracks] == [GUIDE_ID, "guide2"]
    assert tracks[0].track_number == 1
    assert tracks[0].duration == 1423
    # compressed audio is preferred over wav
    mapping = next(iter(tracks[0].provider_mappings))
    assert mapping.audio_format.content_type == ContentType.MP4


async def test_get_track_resolves_program(provider: CalmProvider, api: FakeCalmApi) -> None:
    track = await provider.get_track(GUIDE_ID)
    assert track.name == "First"
    assert isinstance(track.album, Album) and track.album.item_id == PROGRAM_ID
    assert f"programs/guides/{GUIDE_ID}" in api.calls


async def test_stream_details(provider: CalmProvider) -> None:
    details = await provider.get_stream_details(GUIDE_ID, MediaType.TRACK)
    assert details.stream_type == StreamType.HTTP
    assert details.path == "https://assets.calm.com/a.m4a"
    assert details.duration == 1423
    assert details.audio_format.content_type == ContentType.MP4


async def test_stream_refused_when_locked(provider: CalmProvider, api: FakeCalmApi) -> None:
    api.unlocked = False
    with pytest.raises(MediaNotFoundError):
        await provider.get_stream_details(GUIDE_ID, MediaType.TRACK)


async def test_search_maps_programs_and_guides(provider: CalmProvider) -> None:
    result = await provider.search("rain", [MediaType.ALBUM, MediaType.TRACK], limit=5)
    assert [a.item_id for a in result.albums] == [PROGRAM_ID]
    assert [t.item_id for t in result.tracks] == [GUIDE_ID]
    # locked items are listed but marked unavailable
    assert not next(iter(result.albums[0].provider_mappings)).available
    assert next(iter(result.tracks[0].provider_mappings)).available
    tracks_only = await provider.search("rain", [MediaType.TRACK])
    assert not tracks_only.albums


async def test_browse_root_lists_feeds(provider: CalmProvider) -> None:
    items = await provider.browse("calm--test://")
    assert all(isinstance(i, BrowseFolder) for i in items)
    assert items[0].path == "calm--test://feed/sleep"


async def test_browse_feed_skips_promos_and_empty_packs(provider: CalmProvider) -> None:
    items = await provider.browse("calm--test://feed/sleep")
    assert [i.path for i in items] == [
        "calm--test://pack/sleep-featured",
        "calm--test://feed/sleep-music",
        "calm--test://pack/tagged-x",
    ]


async def test_browse_pack_items(provider: CalmProvider) -> None:
    items = await provider.browse("calm--test://pack/sleep-featured")
    assert isinstance(items[0], Track) and items[0].item_id == GUIDE_ID
    assert items[0].album is not None and items[0].album.item_id == PROGRAM_ID
    assert isinstance(items[1], Album)
    assert isinstance(items[2], BrowseFolder) and items[2].path == "calm--test://pack/sub"


async def test_library_from_favorites(provider: CalmProvider) -> None:
    albums = [a async for a in provider.get_library_albums()]
    tracks = [t async for t in provider.get_library_tracks()]
    assert [a.item_id for a in albums] == [PROGRAM_ID]
    assert [t.item_id for t in tracks] == [GUIDE_ID]


async def test_recommendations(provider: CalmProvider) -> None:
    rows = await provider.get_recommendations()
    assert [r.item_id for r in rows] == ["pack/sleep-featured"]
    items = await provider.get_recommendation_items(rows[0].item_id)
    assert len(items) == 3


