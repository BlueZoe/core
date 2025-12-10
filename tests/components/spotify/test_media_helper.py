"""Unit tests for the Spotify media helper."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from spotifyaio.exceptions import SpotifyConnectionError

from homeassistant.components.media_player import BrowseError, MediaType
from homeassistant.components.spotify import media_helper
from homeassistant.components.spotify.models import ItemPayload


@pytest.fixture
def spotify_client() -> MagicMock:
    """Mock Spotify client fixture."""
    client = MagicMock()
    # Mock basic attributes
    client.api_host = "api.spotify.com"
    client.request_timeout = 10
    client.session = MagicMock()

    # Mark all async methods used in code as AsyncMock
    client.refresh_token = AsyncMock()
    client.are_tracks_saved = AsyncMock()
    client.save_tracks = AsyncMock()
    client.remove_saved_tracks = AsyncMock()

    return client


# --- Test 1: enrich_tracks_liked (Basic Logic) ---


@pytest.mark.asyncio
async def test_enrich_tracks_liked_success(spotify_client) -> None:
    """Test enriching tracks with liked status successfully."""
    items = [
        ItemPayload(id="track1", type=MediaType.TRACK, name="Song 1"),
        ItemPayload(id="track2", type=MediaType.TRACK, name="Song 2"),
        ItemPayload(id="album1", type=MediaType.ALBUM, name="Album 1"),
    ]

    spotify_client.are_tracks_saved.return_value = {"track1": True, "track2": False}

    enriched_items = await media_helper.enrich_tracks_liked(spotify_client, items)

    assert enriched_items[0]["is_saved"] is True
    assert enriched_items[1]["is_saved"] is False
    assert "is_saved" not in enriched_items[2]

    spotify_client.are_tracks_saved.assert_called_once_with(["track1", "track2"])


@pytest.mark.asyncio
async def test_enrich_tracks_liked_error(spotify_client) -> None:
    """Test enriching tracks handles API errors gracefully."""
    items = [ItemPayload(id="track1", type=MediaType.TRACK)]

    # Mock API raising an exception
    spotify_client.are_tracks_saved.side_effect = SpotifyConnectionError

    enriched_items = await media_helper.enrich_tracks_liked(spotify_client, items)

    assert enriched_items[0]["is_saved"] is False


# --- Test 2: enrich_tracks_liked (Batching Logic > 50 items) ---
# This is the test case for the 50-item limit
@pytest.mark.asyncio
async def test_enrich_tracks_liked_batching(spotify_client) -> None:
    """Test that enrich_tracks_liked correctly batches requests for >50 tracks."""
    # 1. Generate 55 items (over the 50 limit)
    items = [
        ItemPayload(id=f"track_{i}", type=MediaType.TRACK, name=f"Song {i}")
        for i in range(55)
    ]

    # 2. Mock dynamic response based on input IDs
    async def mock_are_tracks_saved_side_effect(ids):
        return dict.fromkeys(ids, True)

    spotify_client.are_tracks_saved.side_effect = mock_are_tracks_saved_side_effect

    # 3. Execute
    enriched_items = await media_helper.enrich_tracks_liked(spotify_client, items)

    # 4. Verify all items are processed
    assert len(enriched_items) == 55
    assert all(item["is_saved"] for item in enriched_items)

    # 5. Verify API was called twice (Batching occurred)
    assert spotify_client.are_tracks_saved.call_count == 2

    calls = spotify_client.are_tracks_saved.call_args_list

    # Check Batch 1 (0-49)
    batch_1_ids = calls[0].args[0]
    assert len(batch_1_ids) == 50
    assert batch_1_ids[0] == "track_0"
    assert batch_1_ids[-1] == "track_49"

    # Check Batch 2 (50-54)
    batch_2_ids = calls[1].args[0]
    assert len(batch_2_ids) == 5
    assert batch_2_ids[0] == "track_50"


# --- Test 3: handle_liked_songs_action (Add/Remove) ---


@pytest.mark.asyncio
async def test_handle_liked_songs_action_add(spotify_client) -> None:
    """Test adding a track to liked songs."""
    media_id = "spotify:track:12345"
    query_params = {"action": "true"}

    result = await media_helper.handle_liked_songs_action(
        spotify_client, media_id, query_params
    )

    spotify_client.save_tracks.assert_called_once_with(["12345"])
    assert result.title == "success:added"


@pytest.mark.asyncio
async def test_handle_liked_songs_action_remove(spotify_client) -> None:
    """Test removing a track from liked songs."""
    media_id = "spotify:track:12345"
    query_params = {"action": "false"}

    result = await media_helper.handle_liked_songs_action(
        spotify_client, media_id, query_params
    )

    spotify_client.remove_saved_tracks.assert_called_once_with(["12345"])
    assert result.title == "success:removed"


@pytest.mark.asyncio
async def test_handle_liked_songs_action_invalid_uri(spotify_client) -> None:
    """Test handling invalid URI."""
    media_id = "invalid_uri_input"
    query_params = {"action": "true"}

    # Patch 'get_identifier' to force return None
    with (
        patch(
            "homeassistant.components.spotify.media_helper.get_identifier",
            return_value=None,
        ),
        pytest.raises(BrowseError),
    ):
        await media_helper.handle_liked_songs_action(
            spotify_client, media_id, query_params
        )


# --- Test 4: search_tracks (Search & Parse) ---


@pytest.mark.asyncio
async def test_search_tracks_success(spotify_client) -> None:
    """Test searching tracks functionality."""
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(
        return_value="""
    {
        "tracks": {
            "items": [
                {
                    "id": "track1",
                    "name": "Test Song",
                    "uri": "spotify:track:track1",
                    "album": {
                        "images": [{}, {"url": "http://image.url"}]
                    }
                }
            ]
        }
    }
    """
    )

    mock_get_ctx = AsyncMock()
    mock_get_ctx.__aenter__.return_value = mock_response
    mock_get_ctx.__aexit__.return_value = None

    spotify_client.session.get.return_value = mock_get_ctx

    # Patch enrich_tracks_liked to avoid dependency on that logic here
    with patch(
        "homeassistant.components.spotify.media_helper.enrich_tracks_liked"
    ) as mock_enrich:
        mock_enrich.side_effect = lambda client, items: items

        results = await media_helper.search_tracks(spotify_client, "query")

        assert len(results) == 1
        assert results[0]["id"] == "track1"
        assert results[0]["thumbnail"] == "http://image.url"

        # Verify refresh_token was awaited
        spotify_client.refresh_token.assert_called_once()
