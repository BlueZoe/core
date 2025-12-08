"""Media helper functions for Spotify."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp
from spotifyaio import SpotifyClient
from spotifyaio.exceptions import SpotifyConnectionError
from spotifyaio.util import get_identifier
from yarl import URL

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaClass,
    MediaType,
)

from .const import MEDIA_PLAYER_PREFIX
from .models import ItemPayload
from .util import spotify_uri_from_media_browser_url

_LOGGER = logging.getLogger(__name__)


async def enrich_tracks_liked(
    spotify: SpotifyClient, items: list[ItemPayload]
) -> list[ItemPayload]:
    """Enrich a list of track ItemPayload objects with liked status.

    Args:
        spotify: Authenticated SpotifyClient
        items: List of ItemPayload objects (must have "id" field for tracks)

    Returns:
        List of ItemPayload objects with is_saved field populated for tracks
    """
    if not items:
        return items

    # Collect track IDs from items
    track_ids_to_check = [
        track_id
        for item in items
        if item.get("type") == MediaType.TRACK and (track_id := item.get("id"))
    ]

    if not track_ids_to_check:
        return items

    # Batch check which tracks are liked (Spotify API limit: 50 per request)
    MAX_IDS_PER_REQUEST = 50
    liked_status: dict[str, bool] = {}

    for i in range(0, len(track_ids_to_check), MAX_IDS_PER_REQUEST):
        batch = track_ids_to_check[i : i + MAX_IDS_PER_REQUEST]
        try:
            batch_result = await spotify.are_tracks_saved(batch)
            liked_status.update(batch_result)
        except (SpotifyConnectionError, AttributeError, KeyError, ValueError) as err:
            _LOGGER.warning("Failed to check liked tracks: %s", err, exc_info=True)
            # Mark all tracks in batch as not liked on error
            for track_id in batch:
                liked_status[track_id] = False

    # Enrich items with liked status
    for item in items:
        if item.get("type") == MediaType.TRACK and (track_id := item.get("id")):
            # Add is_saved field to existing item
            item["is_saved"] = liked_status.get(track_id, False)

    return items


async def search_tracks(
    spotify: SpotifyClient,
    query: str,
    limit: int = 48,
) -> list[ItemPayload]:
    """Search for tracks and include liked status and album images.

    Args:
        spotify: Authenticated SpotifyClient
        query: Search query string
        limit: Maximum number of results to return

    Returns:
        List of ItemPayload objects with is_saved field populated
    """
    # Prepare API request following spotifyaio patterns
    url = URL.build(
        scheme="https",
        host=spotify.api_host,
        port=443,
    ).joinpath("v1/search")

    await spotify.refresh_token()
    token = getattr(spotify, "_token", None)
    if not token:
        _LOGGER.debug("No authentication token available")
        return []

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
    }

    if spotify.session is None:
        spotify.session = aiohttp.ClientSession()

    search_params: dict[str, str | int] = {
        "q": query,
        "type": "track",
        "limit": limit,
    }

    try:
        # Execute search request with timeout
        async with asyncio.timeout(spotify.request_timeout):
            async with spotify.session.get(
                url,
                headers=headers,
                params=search_params,
            ) as resp:
                if resp.status == 204:
                    return []

                if resp.status != 200:
                    _LOGGER.warning(
                        "Failed to search tracks with images: HTTP %s", resp.status
                    )
                    return []

                text = await resp.text()

                if '"status": 404' in text:
                    _LOGGER.debug("Search returned 404")
                    return []

                # Parse response and extract track data
                data = json.loads(text)
                tracks_data = data.get("tracks", {}).get("items", [])

                # Build ItemPayload objects with album images
                items: list[ItemPayload] = []
                for track_data in tracks_data:
                    if not track_data:
                        continue
                    track_id = track_data.get("id")
                    if not track_id:
                        continue

                    # Extract album image (middle size)
                    img_url = None
                    album_data = track_data.get("album")
                    if album_data and album_data.get("images"):
                        img_url = album_data["images"][1]["url"]

                    items.append(
                        ItemPayload(
                            id=track_id,
                            name=track_data["name"],
                            type=MediaType.TRACK,
                            uri=track_data["uri"],
                            thumbnail=img_url,
                        )
                    )

                # Enrich items with liked status
                return await enrich_tracks_liked(spotify, items)

    except TimeoutError as err:
        msg = "Timeout occurred while searching tracks"
        raise SpotifyConnectionError(msg) from err
    except (aiohttp.ClientError, KeyError, ValueError, json.JSONDecodeError) as err:
        _LOGGER.warning("Error searching tracks with images: %s", err, exc_info=True)
        return []


async def handle_liked_songs_action(
    spotify: SpotifyClient,
    media_content_id: str,
    query_params: dict[str, Any],
) -> BrowseMedia:
    """Handle liked songs action (add/remove track from user's library).

    Response title format:
    - Success: "success:added" or "success:removed"
    - Error: "error:Failed to {action} track from liked songs: {error_msg}"

    Args:
        spotify: Authenticated SpotifyClient
        media_content_id: Track URI (e.g., "spotify:track:4uLU6hMCjMI75M1A2tKUQC")
        query_params: Query parameters with 'action' key (true/false string or bool)

    Returns:
        BrowseMedia response with status encoded in title for frontend parsing

    Raises:
        BrowseError: If track URI is invalid
    """
    # Parse action parameter (yarl returns list, handle both list and direct values)
    action_param = query_params.get("action", ["true"])
    if isinstance(action_param, list):
        action_param = action_param[0] if action_param else "true"
    action = (
        action_param
        if isinstance(action_param, bool)
        else action_param.lower() == "true"
    )

    # Extract track ID from URI
    original_uri = spotify_uri_from_media_browser_url(media_content_id)
    track_id = get_identifier(original_uri)
    if not track_id:
        raise BrowseError(f"Invalid track URI: {media_content_id}")

    action_str = "add" if action else "remove"
    _LOGGER.info(
        "Spotify liked songs %s: original_uri=%s, track_id=%s",
        action_str,
        original_uri,
        track_id,
    )

    # Execute add/remove action via SpotifyAIO
    func = spotify.save_tracks if action else spotify.remove_saved_tracks
    try:
        await func([track_id])
        _LOGGER.info(
            "Spotify API response for %s track %s: success", action_str, track_id
        )

        # Return success response with status in title for frontend parsing
        status = "added" if action else "removed"
        return _create_browse_media_response(media_content_id, f"success:{status}")
    except SpotifyConnectionError as err:
        error_msg = str(err) if str(err) else "Connection error"
        _LOGGER.error(
            "Spotify API error when trying to %s track %s: %s",
            action_str,
            track_id,
            error_msg,
        )
        return _create_browse_media_response(
            media_content_id,
            f"error:Failed to {action_str} track from liked songs: {error_msg}",
        )
    except Exception as err:
        error_msg = str(err) if str(err) else "Unknown error"
        _LOGGER.exception(
            "Unexpected error when trying to %s track %s", action_str, track_id
        )
        return _create_browse_media_response(
            media_content_id,
            f"error:Failed to {action_str} track from liked songs: {error_msg}",
        )


def _create_browse_media_response(media_content_id: str, title: str) -> BrowseMedia:
    """Create a BrowseMedia response with the given title.

    Used for liked songs action responses to communicate status to frontend.

    Args:
        media_content_id: Track URI
        title: Response title (format: "success:status" or "error:message")

    Returns:
        BrowseMedia instance with status encoded in title
    """
    return BrowseMedia(
        title=title,
        media_class=MediaClass.TRACK,
        media_content_id=media_content_id,
        media_content_type=f"{MEDIA_PLAYER_PREFIX}{MediaType.TRACK}",
        can_play=False,
        can_expand=False,
    )
