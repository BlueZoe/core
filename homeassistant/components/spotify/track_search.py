"""Track search helper with album images included."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, TypedDict

import aiohttp
from spotifyaio import SpotifyClient
from spotifyaio.exceptions import SpotifyConnectionError
from yarl import URL

from homeassistant.components.media_player import MediaType

if TYPE_CHECKING:
    from .browse_media import ItemPayload
else:
    # Define ItemPayload locally to match browse_media.ItemPayload structure
    class ItemPayload(TypedDict):
        """TypedDict for item payload."""

        name: str
        type: str
        uri: str
        id: str | None
        thumbnail: str | None


_LOGGER = logging.getLogger(__name__)


async def search_tracks_with_images(
    spotify: SpotifyClient,
    query: str,
    limit: int = 48,
) -> list[ItemPayload]:
    """Search for tracks with album images included in a single API call.

    This function makes a direct API call to Spotify's search endpoint which
    returns full track objects (with album info) and converts them to ItemPayload.

    Args:
        spotify: Authenticated SpotifyClient
        query: Search query string
        limit: Number of results to return (max 50)

    Returns:
        List of ItemPayload objects ready to be used in browse_media.
    """
    # Build URL following spotifyaio pattern
    url = URL.build(
        scheme="https",
        host=spotify.api_host,
        port=443,
    ).joinpath("v1/search")

    # Ensure token is refreshed (following spotifyaio pattern)
    await spotify.refresh_token()

    # Build headers following spotifyaio pattern
    token = getattr(spotify, "_token", None)
    if not token:
        _LOGGER.debug("No authentication token available")
        return []

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
    }

    # Ensure session exists (following spotifyaio pattern)
    if spotify.session is None:
        spotify.session = aiohttp.ClientSession()

    # Build search parameters
    search_params: dict[str, str | int] = {
        "q": query,
        "type": "track",
        "limit": limit,
    }

    try:
        # Make request following spotifyaio pattern with timeout
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

                # Check for 404 in response (following spotifyaio pattern)
                if '"status": 404' in text:
                    _LOGGER.debug("Search returned 404")
                    return []

                # Parse JSON response
                data = json.loads(text)
                tracks_data = data.get("tracks", {}).get("items", [])

                # Convert to ItemPayload format (ready for browse_media)
                items: list[ItemPayload] = []
                for track_data in tracks_data:
                    if not track_data:
                        continue

                    # Get album image URL (middle image)
                    img_url = None
                    album_data = track_data.get("album")
                    if album_data and album_data.get("images"):
                        img_url = album_data["images"][1]["url"]

                    # Build ItemPayload
                    item: ItemPayload = {
                        "id": track_data["id"],
                        "name": track_data["name"],
                        "type": MediaType.TRACK,
                        "uri": track_data["uri"],
                        "thumbnail": img_url,
                    }
                    items.append(item)

                return items

    except TimeoutError as err:
        msg = "Timeout occurred while searching tracks"
        raise SpotifyConnectionError(msg) from err
    except (aiohttp.ClientError, KeyError, ValueError, json.JSONDecodeError) as err:
        _LOGGER.warning("Error searching tracks with images: %s", err, exc_info=True)
        return []
