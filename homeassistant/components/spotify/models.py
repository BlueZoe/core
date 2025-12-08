"""Models for use in Spotify integration."""

from dataclasses import dataclass
from typing import TypedDict

from spotifyaio import Device

from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .coordinator import SpotifyCoordinator


class ItemPayload(TypedDict, total=False):
    """TypedDict for item payload."""

    name: str
    type: str
    uri: str
    id: str | None
    thumbnail: str | None
    is_saved: bool  # Optional field indicating if track is in user's saved songs


@dataclass
class SpotifyData:
    """Class to hold Spotify data."""

    coordinator: SpotifyCoordinator
    session: OAuth2Session
    devices: DataUpdateCoordinator[list[Device]]
