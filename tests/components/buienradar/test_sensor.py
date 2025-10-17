"""The tests for the Buienradar sensor platform."""

from http import HTTPStatus

from homeassistant.components.buienradar.const import DOMAIN
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry
from tests.test_util.aiohttp import AiohttpClientMocker

TEST_LONGITUDE = 51.5288504
TEST_LATITUDE = 5.4002156

CONDITIONS = ["stationname", "temperature"]
TEST_CFG_DATA = {CONF_LATITUDE: TEST_LATITUDE, CONF_LONGITUDE: TEST_LONGITUDE}


async def test_smoke_test_setup_component(
    aioclient_mock: AiohttpClientMocker,
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
) -> None:
    """Smoke test for successfully set-up with default config."""
    aioclient_mock.get(
        "https://data.buienradar.nl/2.0/feed/json", status=HTTPStatus.NOT_FOUND
    )
    mock_entry = MockConfigEntry(domain=DOMAIN, unique_id="TEST_ID", data=TEST_CFG_DATA)

    mock_entry.add_to_hass(hass)

    for cond in CONDITIONS:
        entity_registry.async_get_or_create(
            domain="sensor",
            platform="buienradar",
            unique_id=f"{TEST_LATITUDE:2.6f}{TEST_LONGITUDE:2.6f}{cond}",
            config_entry=mock_entry,
            original_name=f"Buienradar {cond}",
        )
    await hass.async_block_till_done()

    await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    for cond in CONDITIONS:
        state = hass.states.get(f"sensor.buienradar_5_40021651_528850{cond}")
        assert state.state == "unknown"

def test_icon_constants_usage_for_all_icons():
    """Test that all defined icon constants are correctly used in sensor descriptions."""
    from homeassistant.components.buienradar.const import (
        ICON_GAUGE,
        ICON_COMPASS_OUTLINE,
        ICON_WEATHER_POURING,
        ICON_WEATHER_PARTLY_CLOUDY,
    )
    from homeassistant.components.buienradar import sensor

    icons_to_expected_counts = {
        ICON_GAUGE: 4,
        ICON_COMPASS_OUTLINE: 11,
        ICON_WEATHER_POURING: 5,
        ICON_WEATHER_PARTLY_CLOUDY: 5,
    }

    # 校验常量值正确
    assert ICON_GAUGE == "mdi:gauge"
    assert ICON_COMPASS_OUTLINE == "mdi:compass-outline"
    assert ICON_WEATHER_POURING == "mdi:weather-pouring"
    assert ICON_WEATHER_PARTLY_CLOUDY == "mdi:weather-partly-cloudy"

    # 校验使用次数与内容正确
    for icon_const, expected_count in icons_to_expected_counts.items():
        used = [
            desc for desc in sensor.SENSOR_TYPES if getattr(desc, "icon", None) == icon_const
        ]
        assert len(used) == expected_count, f"{icon_const} used {len(used)} times, expected {expected_count}"
        assert all(desc.icon == icon_const for desc in used)

