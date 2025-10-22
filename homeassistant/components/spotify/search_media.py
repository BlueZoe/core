"""Support for global Spotify media searching."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import cast

from spotifyaio import (
    Artist,
    BasePlaylist,
    SimplifiedAlbum,
    SimplifiedTrack,
    SpotifyClient,
)

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    SearchMediaQuery,
)
from homeassistant.core import HomeAssistant

from .browse_media import (
    ItemPayload,
    MissingMediaInformation,
    UnknownMediaType,
    _get_album_item_payload,
    _get_artist_item_payload,
    _get_playlist_item_payload,
    _get_track_item_payload,
    item_payload,
)

_LOGGER = logging.getLogger(__name__)

# Maximum number of items we keep from the raw Spotify search response.
# This is aligned with the browse payload limit so we do not spam the UI.
SEARCH_LIMIT = 48

# Mapping from Home Assistant media classes to Spotify search types.
# Home Assistant passes us a list of MediaClass values, but the Spotify
# search endpoint expects strings like "track", "album", etc.
_MEDIA_CLASS_TO_SPOTIFY_TYPE: dict[MediaClass, str] = {
    MediaClass.ARTIST: "artist",
    MediaClass.ALBUM: "album",
    MediaClass.TRACK: "track",
    MediaClass.MUSIC: "track",
    MediaClass.PLAYLIST: "playlist",
}


async def async_search_media_internal(
    hass: HomeAssistant,
    spotify: SpotifyClient,
    query: SearchMediaQuery,
) -> list[BrowseMedia]:
    """Perform a global search on Spotify and return a flat result list.

    High-level flow:
    - Read search text from `query.search_query`.
    - Convert Home Assistant filter classes into Spotify search types.
    - Call `spotify.search(...)`.
    - Convert the response into a list of BrowseMedia items.

    The return type is a plain list, as expected by the
    `media_player.search_media` API.
    """
    search_query = (query.search_query or "").strip()
    if not search_query:
        _LOGGER.debug("Received empty search query for global search")
        return []

    filter_classes = _normalize_filter_classes(query.media_filter_classes)
    spotify_types = _build_spotify_types(filter_classes)
    if not spotify_types:
        _LOGGER.debug(
            "No supported media classes in filter %s; returning empty search result",
            filter_classes,
        )
        return []

    _LOGGER.debug(
        "Running global Spotify search for %s with types %s",
        search_query,
        spotify_types,
    )

    # NOTE: `spotifyaio.search` may return a dict-like structure or a typed
    # object with attributes (e.g. `tracks.items`). `_iterate_results` is
    # written to handle both shapes.
    search_response = await spotify.search(
        query=search_query,
        types=spotify_types,  # type: ignore[arg-type]
        limit=SEARCH_LIMIT,
    )

    _LOGGER.debug("Spotify raw search response: %r", search_response)

    items: list[ItemPayload] = []
    # Used to avoid returning the same URI multiple times across sections.
    seen_uris: set[str] = set()

    # Tracks
    if "track" in spotify_types:
        items.extend(
            _get_track_item_payload(cast(SimplifiedTrack, track))
            for track in _iterate_results(search_response, "tracks")
        )

    # Albums
    if "album" in spotify_types:
        items.extend(
            _get_album_item_payload(cast(SimplifiedAlbum, album))
            for album in _iterate_results(search_response, "albums")
        )

    # Artists
    if "artist" in spotify_types:
        items.extend(
            _get_artist_item_payload(cast(Artist, artist))
            for artist in _iterate_results(search_response, "artists")
        )

    # Playlists
    if "playlist" in spotify_types:
        items.extend(
            _get_playlist_item_payload(cast(BasePlaylist, playlist))
            for playlist in _iterate_results(search_response, "playlists")
        )

    if len(items) > SEARCH_LIMIT:
        items = items[:SEARCH_LIMIT]

    results: list[BrowseMedia] = []
    for payload in items:
        uri = payload.get("uri")
        if not uri or uri in seen_uris:
            continue
        seen_uris.add(uri)

        try:
            results.append(
                item_payload(
                    payload,
                    can_play_artist=True,
                )
            )
        except (MissingMediaInformation, UnknownMediaType):
            _LOGGER.debug("Skipping invalid global search payload: %s", payload)

    return results


def _normalize_filter_classes(
    media_filter_classes: list[MediaClass] | None,
) -> set[MediaClass]:
    """Normalize and default the filter classes for search.

    When no filters are provided, we search across the most common
    music-related classes: artists, albums, tracks and playlists.
    """
    if not media_filter_classes:
        return {
            MediaClass.ARTIST,
            MediaClass.ALBUM,
            MediaClass.TRACK,
            MediaClass.PLAYLIST,
        }
    return set(media_filter_classes)


def _build_spotify_types(filter_classes: set[MediaClass]) -> list[str]:
    """Build the list of Spotify search type strings from media classes.

    Example:
    - {MediaClass.ARTIST, MediaClass.TRACK} -> ["artist", "track"]
    """
    types: list[str] = []
    for media_class in filter_classes:
        spotify_type = _MEDIA_CLASS_TO_SPOTIFY_TYPE.get(media_class)
        if spotify_type and spotify_type not in types:
            types.append(spotify_type)
    return types


def _iterate_results(
    search_response: object,
    key: str,
) -> Iterable[object]:
    """Iterate over items in one section of the search response.

    The function is intentionally defensive:
    - If `search_response` is a dict, it assumes a JSON-like structure,
      e.g. `response["tracks"]["items"]`.
    - If it is an object, it tries attribute access, e.g. `response.tracks.items`.

    This keeps the integration resilient to small changes in the
    `spotifyaio` data model.
    """
    # Dict-like response (Spotify Web API JSON: {"tracks": {"items": [...]}, ...}).
    if isinstance(search_response, dict):
        section = search_response.get(key) or {}
        return cast(Iterable[object], section.get("items") or ())

    # Dataclass / object response with attributes (e.g. `tracks.items`).
    section = getattr(search_response, key, None)
    if section is None:
        return ()
    items = getattr(section, "items", None)
    if items is None:
        return ()
    return cast(Iterable[object], items)
