"""Support for Buienradar.nl weather service."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
import logging
from typing import Any

from buienradar.constants import (
    ATTRIBUTION,
    CONDCODE,
    CONDITION,
    DETAILED,
    EXACT,
    EXACTNL,
    FORECAST,
    IMAGE,
    MEASURED,
    PRECIPITATION_FORECAST,
    STATIONNAME,
    TIMEFRAME,
    VISIBILITY,
    WINDGUST,
    WINDSPEED,
)

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    DEGREE,
    PERCENTAGE,
    Platform,
    UnitOfIrradiance,
    UnitOfLength,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import BuienRadarConfigEntry
from .const import (
    CONF_TIMEFRAME,
    DEFAULT_TIMEFRAME,
    STATE_CONDITION_CODES,
    STATE_CONDITIONS,
    STATE_DETAILED_CONDITIONS,
    ICON_WEATHER_WINDY,
    ICON_GAUGE,
    ICON_COMPASS_OUTLINE,
    ICON_WEATHER_POURING,
    ICON_WEATHER_PARTLY_CLOUDY,
)
from .util import BrData

_LOGGER = logging.getLogger(__name__)

MEASURED_LABEL = "Measured"
TIMEFRAME_LABEL = "Timeframe"
SYMBOL = "symbol"

# Schedule next call after (minutes):
SCHEDULE_OK = 10
# When an error occurred, new call after (minutes):
SCHEDULE_NOK = 2

STATIONNAME_LABEL = "Stationname"

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="stationname",
        translation_key="stationname",
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="barometerfc",
        translation_key="barometerfc",
        icon=ICON_GAUGE,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="barometerfcname",
        translation_key="barometerfcname",
        icon=ICON_GAUGE,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="barometerfcnamenl",
        translation_key="barometerfcnamenl",
        icon=ICON_GAUGE,
    ),
    SensorEntityDescription(
        key="condition",
        translation_key="condition",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditioncode",
        translation_key="conditioncode",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditiondetailed",
        translation_key="conditiondetailed",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditionexact",
        translation_key="conditionexact",
    ),
    SensorEntityDescription(
        key="symbol",
        translation_key="symbol",
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="feeltemperature",
        translation_key="feeltemperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:water-percent",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="groundtemperature",
        translation_key="groundtemperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="windspeed",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="windforce",
        translation_key="windforce",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="winddirection",
        translation_key="winddirection",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="windazimuth",
        translation_key="windazimuth",
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
    ),
    SensorEntityDescription(
        key="pressure",
        device_class=SensorDeviceClass.PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        icon=ICON_GAUGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="visibility",
        translation_key="visibility",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="windgust",
        translation_key="windgust",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="precipitation",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
    ),
    SensorEntityDescription(
        key="irradiance",
        device_class=SensorDeviceClass.IRRADIANCE,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="precipitation_forecast_average",
        translation_key="precipitation_forecast_average",
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
    ),
    SensorEntityDescription(
        key="precipitation_forecast_total",
        translation_key="precipitation_forecast_total",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="rainlast24hour",
        translation_key="rainlast24hour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="rainlasthour",
        translation_key="rainlasthour",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="temperature_1d",
        translation_key="temperature_1d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="temperature_2d",
        translation_key="temperature_2d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="temperature_3d",
        translation_key="temperature_3d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="temperature_4d",
        translation_key="temperature_4d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="temperature_5d",
        translation_key="temperature_5d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="mintemp_1d",
        translation_key="mintemp_1d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="mintemp_2d",
        translation_key="mintemp_2d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="mintemp_3d",
        translation_key="mintemp_3d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="mintemp_4d",
        translation_key="mintemp_4d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="mintemp_5d",
        translation_key="mintemp_5d",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    SensorEntityDescription(
        key="rain_1d",
        translation_key="rain_1d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="rain_2d",
        translation_key="rain_2d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="rain_3d",
        translation_key="rain_3d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="rain_4d",
        translation_key="rain_4d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="rain_5d",
        translation_key="rain_5d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="minrain_1d",
        translation_key="minrain_1d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="minrain_2d",
        translation_key="minrain_2d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="minrain_3d",
        translation_key="minrain_3d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="minrain_4d",
        translation_key="minrain_4d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="minrain_5d",
        translation_key="minrain_5d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    # new in json api (>1.0.0):
    SensorEntityDescription(
        key="maxrain_1d",
        translation_key="maxrain_1d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="maxrain_2d",
        translation_key="maxrain_2d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="maxrain_3d",
        translation_key="maxrain_3d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="maxrain_4d",
        translation_key="maxrain_4d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="maxrain_5d",
        translation_key="maxrain_5d",
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
    ),
    SensorEntityDescription(
        key="rainchance_1d",
        translation_key="rainchance_1d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_POURING,
    ),
    SensorEntityDescription(
        key="rainchance_2d",
        translation_key="rainchance_2d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_POURING,
    ),
    SensorEntityDescription(
        key="rainchance_3d",
        translation_key="rainchance_3d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_POURING,
    ),
    SensorEntityDescription(
        key="rainchance_4d",
        translation_key="rainchance_4d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_POURING,
    ),
    SensorEntityDescription(
        key="rainchance_5d",
        translation_key="rainchance_5d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_POURING,
    ),
    SensorEntityDescription(
        key="sunchance_1d",
        translation_key="sunchance_1d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_PARTLY_CLOUDY,
    ),
    SensorEntityDescription(
        key="sunchance_2d",
        translation_key="sunchance_2d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_PARTLY_CLOUDY,
    ),
    SensorEntityDescription(
        key="sunchance_3d",
        translation_key="sunchance_3d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_PARTLY_CLOUDY,
    ),
    SensorEntityDescription(
        key="sunchance_4d",
        translation_key="sunchance_4d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_PARTLY_CLOUDY,
    ),
    SensorEntityDescription(
        key="sunchance_5d",
        translation_key="sunchance_5d",
        native_unit_of_measurement=PERCENTAGE,
        icon=ICON_WEATHER_PARTLY_CLOUDY,
    ),
    SensorEntityDescription(
        key="windforce_1d",
        translation_key="windforce_1d",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="windforce_2d",
        translation_key="windforce_2d",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="windforce_3d",
        translation_key="windforce_3d",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="windforce_4d",
        translation_key="windforce_4d",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="windforce_5d",
        translation_key="windforce_5d",
        native_unit_of_measurement="Bft",
        icon=ICON_WEATHER_WINDY,
    ),
    SensorEntityDescription(
        key="windspeed_1d",
        translation_key="windspeed_1d",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="windspeed_2d",
        translation_key="windspeed_2d",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="windspeed_3d",
        translation_key="windspeed_3d",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="windspeed_4d",
        translation_key="windspeed_4d",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="windspeed_5d",
        translation_key="windspeed_5d",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    SensorEntityDescription(
        key="winddirection_1d",
        translation_key="winddirection_1d",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="winddirection_2d",
        translation_key="winddirection_2d",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="winddirection_3d",
        translation_key="winddirection_3d",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="winddirection_4d",
        translation_key="winddirection_4d",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="winddirection_5d",
        translation_key="winddirection_5d",
        icon=ICON_COMPASS_OUTLINE,
    ),
    SensorEntityDescription(
        key="windazimuth_1d",
        translation_key="windazimuth_1d",
        native_unit_of_measurement=DEGREE,
        icon=ICON_COMPASS_OUTLINE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
    ),
    SensorEntityDescription(
        key="windazimuth_2d",
        translation_key="windazimuth_2d",
        native_unit_of_measurement=DEGREE,
        icon=ICON_COMPASS_OUTLINE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
    ),
    SensorEntityDescription(
        key="windazimuth_3d",
        translation_key="windazimuth_3d",
        native_unit_of_measurement=DEGREE,
        icon=ICON_COMPASS_OUTLINE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
    ),
    SensorEntityDescription(
        key="windazimuth_4d",
        translation_key="windazimuth_4d",
        native_unit_of_measurement=DEGREE,
        icon=ICON_COMPASS_OUTLINE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
    ),
    SensorEntityDescription(
        key="windazimuth_5d",
        translation_key="windazimuth_5d",
        native_unit_of_measurement=DEGREE,
        icon=ICON_COMPASS_OUTLINE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
    ),
    SensorEntityDescription(
        key="condition_1d",
        translation_key="condition_1d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="condition_2d",
        translation_key="condition_2d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="condition_3d",
        translation_key="condition_3d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="condition_4d",
        translation_key="condition_4d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="condition_5d",
        translation_key="condition_5d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditioncode_1d",
        translation_key="conditioncode_1d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditioncode_2d",
        translation_key="conditioncode_2d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditioncode_3d",
        translation_key="conditioncode_3d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditioncode_4d",
        translation_key="conditioncode_4d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditioncode_5d",
        translation_key="conditioncode_5d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_CONDITION_CODES,
    ),
    SensorEntityDescription(
        key="conditiondetailed_1d",
        translation_key="conditiondetailed_1d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditiondetailed_2d",
        translation_key="conditiondetailed_2d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditiondetailed_3d",
        translation_key="conditiondetailed_3d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditiondetailed_4d",
        translation_key="conditiondetailed_4d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditiondetailed_5d",
        translation_key="conditiondetailed_5d",
        device_class=SensorDeviceClass.ENUM,
        options=STATE_DETAILED_CONDITIONS,
    ),
    SensorEntityDescription(
        key="conditionexact_1d",
        translation_key="conditionexact_1d",
    ),
    SensorEntityDescription(
        key="conditionexact_2d",
        translation_key="conditionexact_2d",
    ),
    SensorEntityDescription(
        key="conditionexact_3d",
        translation_key="conditionexact_3d",
    ),
    SensorEntityDescription(
        key="conditionexact_4d",
        translation_key="conditionexact_4d",
    ),
    SensorEntityDescription(
        key="conditionexact_5d",
        translation_key="conditionexact_5d",
    ),
    SensorEntityDescription(
        key="symbol_1d",
        translation_key="symbol_1d",
    ),
    SensorEntityDescription(
        key="symbol_2d",
        translation_key="symbol_2d",
    ),
    SensorEntityDescription(
        key="symbol_3d",
        translation_key="symbol_3d",
    ),
    SensorEntityDescription(
        key="symbol_4d",
        translation_key="symbol_4d",
    ),
    SensorEntityDescription(
        key="symbol_5d",
        translation_key="symbol_5d",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BuienRadarConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the buienradar sensor."""
    config = entry.data
    options = entry.options

    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)

    timeframe = options.get(
        CONF_TIMEFRAME, config.get(CONF_TIMEFRAME, DEFAULT_TIMEFRAME)
    )

    if None in (latitude, longitude):
        _LOGGER.error("Latitude or longitude not set in Home Assistant config")
        return

    coordinates = {CONF_LATITUDE: float(latitude), CONF_LONGITUDE: float(longitude)}

    _LOGGER.debug(
        "Initializing buienradar sensor coordinate %s, timeframe %s",
        coordinates,
        timeframe,
    )

    # create weather entities:
    entities = [
        BrSensor(config.get(CONF_NAME, "Buienradar"), coordinates, description)
        for description in SENSOR_TYPES
    ]

    # create weather data:
    data = BrData(hass, coordinates, timeframe, entities)
    entry.runtime_data[Platform.SENSOR] = data
    await data.async_update()

    async_add_entities(entities)


class BrSensor(SensorEntity):
    """Representation of a Buienradar sensor."""

    _attr_entity_registry_enabled_default = False
    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, client_name, coordinates, description: SensorEntityDescription
    ) -> None:
        """Initialize the sensor."""
        self.entity_description = description
        self._data: BrData | None = None
        self._measured = None
        self._attr_unique_id = (
            f"{coordinates[CONF_LATITUDE]:2.6f}{coordinates[CONF_LONGITUDE]:2.6f}"
            f"{description.key}"
        )

        # All continuous sensors should be forced to be updated
        self._attr_force_update = (
            description.key != SYMBOL and not description.key.startswith(CONDITION)
        )

        if description.key.startswith(PRECIPITATION_FORECAST):
            self._timeframe = None

    async def async_added_to_hass(self) -> None:
        """Handle entity being added to hass."""
        if self._data is None:
            return
        self._update()

    @callback
    def data_updated(self, data: BrData):
        """Handle data update."""
        self._data = data
        if not self.hass:
            return
        self._update()

    def _update(self):
        """Update sensor data."""
        _LOGGER.debug("Updating sensor %s", self.entity_id)
        if self._load_data(self._data.data):
            self.async_write_ha_state()

    @callback
    def _load_data(self, data: dict[str, Any]) -> bool:  # noqa: C901
        """Load the sensor with relevant data."""
        # Check if we have a new measurement,
        # otherwise we do not have to update the sensor
        measured = data.get(MEASURED)
        if measured == getattr(self, "_measured", None):
            return False

        self._measured = measured
        sensor_type = self.entity_description.key
        updated = False  # track if state or picture changed

        # ---------- helpers ----------
        def _day_index(k: str) -> int | None:
            """Return 0-based forecast index for *_1d..*_5d keys."""
            if k.endswith(("_1d", "_2d", "_3d", "_4d", "_5d")):
                try:
                    return int(k[-2]) - 1
                except (ValueError, IndexError):
                    return None
            return None

        def _set_state(val: Any) -> None:
            """Set native_value only if it actually changes."""
            nonlocal updated
            if val != getattr(self, "native_value", None):
                self._attr_native_value = val
                updated = True

        def _set_picture(pic: str | None) -> None:
            """Set entity_picture only if it actually changes."""
            nonlocal updated
            if pic is None:
                return
            if pic != getattr(self, "entity_picture", None):
                self._attr_entity_picture = pic
                updated = True

        def _get_forecast_entry(idx: int) -> dict | None:
            """Safely obtain forecast entry or None (avoid IndexError)."""
            fc_list = data.get(FORECAST) or []
            if not isinstance(fc_list, list):
                return None
            return fc_list[idx] if 0 <= idx < len(fc_list) else None

        # mapping for condition/symbol fields (current family)
        cond_family_current: dict[str, Callable[[dict], Any]] = {
            "symbol": lambda c: c.get(EXACTNL),
            "condition": lambda c: c.get(CONDITION),
            "conditioncode": lambda c: c.get(CONDCODE),
            "conditiondetailed": lambda c: c.get(DETAILED),
            "conditionexact": lambda c: c.get(EXACT),
        }

        # ---------- handlers ----------
        def _handle_condition_current() -> bool:
            # update weather symbol & status text
            nonlocal updated
            cond = data.get(CONDITION) or {}
            picker = cond_family_current.get(sensor_type)
            if picker is None:
                return False
            _set_state(picker(cond))
            _set_picture(cond.get(IMAGE))
            return updated

        def _handle_condition_forecast(idx: int) -> bool:
            # update weather symbol & status text
            nonlocal updated
            entry = _get_forecast_entry(idx)
            if not entry or CONDITION not in entry:
                return False
            cond = entry[CONDITION] or {}
            base = sensor_type.rsplit("_", 1)[
                0
            ]  # e.g. "conditioncode_2d" -> "conditioncode"
            picker = cond_family_current.get(base)
            if picker is None:
                return False
            _set_state(picker(cond))
            _set_picture(cond.get(IMAGE))
            return updated

        def _handle_precipitation_forecast() -> bool:
            # update nested precipitation forecast sensors
            nested = data.get(PRECIPITATION_FORECAST) or {}
            self._timeframe = nested.get(TIMEFRAME)
            subkey = sensor_type.replace("precipitation_forecast_", "", 1)
            _set_state(nested.get(subkey))
            return updated  # note: original behavior did not add attributes here

        def _handle_forecast_generic(idx: int) -> bool:
            """Handle generic forecast numeric fields (incl. windspeed_Nd)."""
            # update forecasting sensors:
            entry = _get_forecast_entry(idx)
            if not entry:
                return False
            base_key = sensor_type.rsplit("_", 1)[
                0
            ]  # e.g. "temperature_3d" -> "temperature"
            value = entry.get(base_key)

            if sensor_type.startswith("windspeed_") and value is not None:
                # hass wants windspeeds in km/h not m/s, so convert:
                with suppress(ValueError, TypeError):
                    value = round(float(value) * 3.6, 1)

            _set_state(value)
            return updated

        def _maybe_convert_after_first(value: Any, factor: float, op: str = "*") -> Any:
            """Convert value only when self.state already exists (2nd and later updates)."""
            if value is None:
                return value
            if getattr(self, "state", None) is None:
                return value
            try:
                fval = float(value)
                return round(fval * factor, 1) if op == "*" else round(fval / factor, 1)
            except (ValueError, TypeError):
                return value

        def _handle_wind_nonforecast(name: str) -> bool:
            # hass wants windspeeds in km/h not m/s, so convert:
            raw = data.get(name)
            conv = _maybe_convert_after_first(raw, 3.6, "*")
            _set_state(conv if raw is not None else None)
            return updated

        def _handle_visibility_nonforecast() -> bool:
            # hass wants visibility in km (not m), so convert:
            raw = data.get(VISIBILITY)
            conv = _maybe_convert_after_first(raw, 1000.0, "/")
            _set_state(conv if raw is not None else None)
            return updated

        def _handle_generic() -> bool:
            # update all other sensors
            _set_state(data.get(sensor_type))

            # attributes population (identical to original)
            attrs = dict(getattr(self, "_attr_extra_state_attributes", {}) or {})
            if ATTRIBUTION in data:
                attrs["attribution"] = data[ATTRIBUTION]
            if STATIONNAME in data:
                attrs[STATIONNAME_LABEL] = data[STATIONNAME]
            measured_val = getattr(self, "_measured", None)
            if measured_val is not None:
                # convert datetime (Europe/Amsterdam) into local datetime
                attrs[MEASURED_LABEL] = dt_util.as_local(measured_val).strftime("%c")
            self._attr_extra_state_attributes = attrs
            return updated

        # ---------- dispatch ----------
        idx = _day_index(sensor_type)
        if idx is not None:
            # update forecasting sensors:
            if sensor_type.startswith(("symbol_", "condition")):
                return _handle_condition_forecast(idx)
            return _handle_forecast_generic(idx)

        if sensor_type in cond_family_current:
            return _handle_condition_current()

        if sensor_type.startswith(PRECIPITATION_FORECAST):
            return _handle_precipitation_forecast()

        if sensor_type in (WINDSPEED, WINDGUST):
            return _handle_wind_nonforecast(sensor_type)

        if sensor_type == VISIBILITY:
            return _handle_visibility_nonforecast()

        return _handle_generic()
