"""The hello_world integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the hello_world integration."""
    hass.states.async_set(f"{DOMAIN}.Hello_World", "Works!")
    return True
