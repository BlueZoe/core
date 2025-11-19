"""Support for local Spotify media searching."""

from __future__ import annotations

from collections.abc import Iterable
import logging

from spotifyaio import SpotifyClient

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
from .const import MEDIA_PLAYER_PREFIX

_LOGGER = logging.getLogger(__name__)

# Maximum number of results we send back to the UI.
# This is kept in sync with the browse payload limit so we do not overload
# the frontend with too many items at once.
SEARCH_LIMIT = 48


async def async_local_search_media_internal(
    hass: HomeAssistant,
    spotify: SpotifyClient,
    query: SearchMediaQuery,
) -> BrowseMedia:
    """Search the user's Spotify library and return a BrowseMedia tree.

    High-level idea:
    - Read `query.search_query` as plain text.
    - Look through the user's library (playlists, artists, albums, tracks).
    - Collect all matches and wrap them in a single BrowseMedia root node.

    The result structure is intentionally the same shape as the one used by
    `async_browse_media`, so the frontend can handle both in a consistent way.
    """
    search_query = (query.search_query or "").strip()
    if not search_query:
        _LOGGER.debug("Received empty search query, returning empty result")
        return _build_empty_result_root()

    # Use a lower-cased copy for simple case-insensitive comparisons.
    search_text = search_query.casefold()
    filter_classes = _normalize_filter_classes(query.media_filter_classes)

    items: list[ItemPayload] = []
    # Used to make sure we do not return the same URI more than once.
    seen_uris: set[str] = set()

    if MediaClass.PLAYLIST in filter_classes:
        await _collect_playlists(spotify, search_text, items, seen_uris)

    if MediaClass.ARTIST in filter_classes:
        await _collect_artists(spotify, search_text, items, seen_uris)

    if MediaClass.ALBUM in filter_classes:
        await _collect_albums(spotify, search_text, items, seen_uris)

    if MediaClass.TRACK in filter_classes:
        await _collect_tracks(spotify, search_text, items, seen_uris)

    if len(items) > SEARCH_LIMIT:
        items = items[:SEARCH_LIMIT]

    return _build_result_root(items, search_query)


def _normalize_filter_classes(
    media_filter_classes: list[MediaClass] | None,
) -> set[MediaClass]:
    """Normalize and default the filter classes for search.

    If the caller does not provide any filter classes, we assume that they
    want to search everything in the local library (playlists, artists,
    albums and tracks).
    """
    if not media_filter_classes:
        return {
            MediaClass.PLAYLIST,
            MediaClass.ARTIST,
            MediaClass.ALBUM,
            MediaClass.TRACK,
        }

    return set(media_filter_classes)


async def _collect_playlists(
    spotify: SpotifyClient,
    search_text: str,
    items: list[ItemPayload],
    seen_uris: set[str],
) -> None:
    """Collect playlist search results from the current user's playlists."""
    playlists = await spotify.get_playlists_for_current_user()
    if not playlists:
        return

    matched = [
        playlist for playlist in playlists if _matches_text(playlist.name, search_text)
    ]
    _add_unique_items(
        items,
        (_get_playlist_item_payload(playlist) for playlist in matched),
        seen_uris,
    )


async def _collect_artists(
    spotify: SpotifyClient,
    search_text: str,
    items: list[ItemPayload],
    seen_uris: set[str],
) -> None:
    """Collect artist search results from followed and top artists.

    We combine:
    - artists the user follows
    - top artists from the user's listening history
    """
    followed = await spotify.get_followed_artists()
    if followed:
        matched_followed = [
            artist for artist in followed if _matches_text(artist.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_artist_item_payload(artist) for artist in matched_followed),
            seen_uris,
        )

    top_artists = await spotify.get_top_artists()
    if top_artists:
        matched_top = [
            artist for artist in top_artists if _matches_text(artist.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_artist_item_payload(artist) for artist in matched_top),
            seen_uris,
        )


async def _collect_albums(
    spotify: SpotifyClient,
    search_text: str,
    items: list[ItemPayload],
    seen_uris: set[str],
) -> None:
    """Collect album search results from saved albums and new releases.

    This gives the user a mix of:
    - albums they already saved
    - albums from the new releases feed
    """
    saved_albums = await spotify.get_saved_albums()
    if saved_albums:
        matched_saved = [
            saved_album.album
            for saved_album in saved_albums
            if _matches_text(saved_album.album.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_album_item_payload(album) for album in matched_saved),
            seen_uris,
        )

    new_releases = await spotify.get_new_releases()
    if new_releases:
        matched_new = [
            album for album in new_releases if _matches_text(album.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_album_item_payload(album) for album in matched_new),
            seen_uris,
        )


async def _collect_tracks(
    spotify: SpotifyClient,
    search_text: str,
    items: list[ItemPayload],
    seen_uris: set[str],
) -> None:
    """Collect track search results from saved, recent and top tracks.

    We search across:
    - tracks the user saved
    - tracks the user played recently
    - the user's top tracks
    """
    saved_tracks = await spotify.get_saved_tracks()
    if saved_tracks:
        matched_saved = [
            saved_track.track
            for saved_track in saved_tracks
            if _matches_text(saved_track.track.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_track_item_payload(track) for track in matched_saved),
            seen_uris,
        )

    recently_played = await spotify.get_recently_played_tracks()
    if recently_played:
        matched_recent = [
            played.track
            for played in recently_played
            if _matches_text(played.track.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_track_item_payload(track) for track in matched_recent),
            seen_uris,
        )

    top_tracks = await spotify.get_top_tracks()
    if top_tracks:
        matched_top = [
            track for track in top_tracks if _matches_text(track.name, search_text)
        ]
        _add_unique_items(
            items,
            (_get_track_item_payload(track) for track in matched_top),
            seen_uris,
        )


def _matches_text(value: str | None, search_text: str) -> bool:
    """Return True if `search_text` is a substring of `value` (case-insensitive)."""
    if not value:
        return False
    return search_text in value.casefold()


def _add_unique_items(
    items: list[ItemPayload],
    new_items: Iterable[ItemPayload],
    seen_uris: set[str],
) -> None:
    """Add new items to the result list, skipping duplicate URIs.

    We track URIs in `seen_uris` so each Spotify item only appears once in the
    final result, even if multiple sources (e.g. saved + recent) contain it.
    """
    for item in new_items:
        uri = item.get("uri")
        if not uri or uri in seen_uris:
            continue
        seen_uris.add(uri)
        items.append(item)


def _build_result_root(items: list[ItemPayload], search_query: str) -> BrowseMedia:
    """Build the root BrowseMedia node for a non-empty search result.

    The children of this node are the actual media items (tracks, playlists,
    artists, etc.). The root itself is just a container with a title.
    """
    browse_media = BrowseMedia(
        can_expand=True,
        can_play=False,
        children_media_class=None,
        media_class=MediaClass.DIRECTORY,
        media_content_id=f"{MEDIA_PLAYER_PREFIX}search",
        media_content_type=f"{MEDIA_PLAYER_PREFIX}search",
        title=f'Search results for "{search_query}"',
        thumbnail=None,
    )

    browse_media.children = []

    for item in items:
        try:
            browse_media.children.append(
                item_payload(
                    item,
                    can_play_artist=True,
                )
            )
        except (MissingMediaInformation, UnknownMediaType):
            _LOGGER.debug("Skipping item with invalid media payload: %s", item)

    return browse_media


def _build_empty_result_root() -> BrowseMedia:
    """Return an empty, but valid, search result root.

    Frontend code still expects a BrowseMedia object, even when there are
    no matches. In that case we return a simple directory node with a
    "No results" title and no children.
    """
    browse_media = BrowseMedia(
        can_expand=False,
        can_play=False,
        children_media_class=None,
        media_class=MediaClass.DIRECTORY,
        media_content_id=f"{MEDIA_PLAYER_PREFIX}search",
        media_content_type=f"{MEDIA_PLAYER_PREFIX}search",
        title="No results",
        thumbnail=None,
    )
    browse_media.children = []
    return browse_media
