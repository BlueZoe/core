"""Unit tests for BrSensor._load_data behavior."""

from datetime import UTC, datetime, timedelta

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
import pytest

# Target: test _load_data directly without going through Home Assistant lifecycle
from homeassistant.components.buienradar.sensor import (
    MEASURED_LABEL,
    STATIONNAME_LABEL,
    BrSensor,
)
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE

LAT = 52.101234
LON = 5.101234


def _sensor(key: str) -> BrSensor:
    """Create a minimal BrSensor instance for direct _load_data testing."""
    return BrSensor(
        "Test",
        {CONF_LATITUDE: LAT, CONF_LONGITUDE: LON},
        SensorEntityDescription(key=key),
    )


def _t(n: int = 0) -> datetime:
    """Generate a unique MEASURED timestamp (UTC aware)."""
    return datetime.now(UTC) + timedelta(seconds=n)


def test_early_return_same_measured() -> None:
    """Return False when MEASURED is unchanged."""
    s = _sensor("temperature")
    data = {MEASURED: _t(0), "temperature": 12}

    assert s._load_data(data) is True
    # Same MEASURED value should return False (no update)
    assert s._load_data({MEASURED: data[MEASURED], "temperature": 99}) is False


def test_forecast_numeric_field_temperature_3d_ok_and_indexerror() -> None:
    """Handle forecast numeric and short list IndexError path."""
    s = _sensor("temperature_3d")
    data_ok = {MEASURED: _t(0), FORECAST: [{}, {}, {"temperature": 7}]}
    assert s._load_data(data_ok) is True
    assert s.native_value == 7

    # Trigger IndexError branch (forecast list too short)
    data_short = {MEASURED: _t(1), FORECAST: [{}, {}]}
    assert s._load_data(data_short) is False


@pytest.mark.parametrize(
    ("key", "expect_field"),
    [
        ("symbol_2d", EXACTNL),
        ("condition_2d", CONDITION),
        ("conditioncode_2d", CONDCODE),
        ("conditiondetailed_2d", DETAILED),
        ("conditionexact_2d", EXACT),
    ],
)
def test_forecast_condition_family(key: str, expect_field: str) -> None:
    """Test forecasted condition/symbol family (_1d.._5d)."""
    s = _sensor(key)
    cond = {
        CONDITION: "Cloudy",
        EXACTNL: "Zwaar bewolkt",
        CONDCODE: "c",
        DETAILED: "Clouds",
        EXACT: "exact",
        IMAGE: "http://img.png",
    }
    data = {MEASURED: _t(0), FORECAST: [{}, {CONDITION: cond}]}
    assert s._load_data(data) is True
    assert s.native_value == cond[expect_field]
    # Image should also be set
    assert s.entity_picture == cond[IMAGE]

    # Same values (new MEASURED) should not trigger update
    data2 = {MEASURED: _t(1), FORECAST: [{}, {CONDITION: cond}]}
    assert s._load_data(data2) is False


@pytest.mark.parametrize(
    ("key", "expect_field"),
    [
        ("symbol", EXACTNL),
        ("condition", CONDITION),
        ("conditioncode", CONDCODE),
        ("conditiondetailed", DETAILED),
        ("conditionexact", EXACT),
    ],
)
def test_current_condition_family(key: str, expect_field: str) -> None:
    """Test current condition/symbol family (non-forecast)."""
    s = _sensor(key)
    cond = {
        CONDITION: "Sunny",
        EXACTNL: "Zonnig",
        CONDCODE: "s",
        DETAILED: "Clear",
        EXACT: "exact",
        IMAGE: "http://img2.png",
    }
    data = {MEASURED: _t(0), CONDITION: cond}
    assert s._load_data(data) is True
    assert s.native_value == cond[expect_field]
    assert s.entity_picture == cond[IMAGE]

    # Same condition should not update
    data_same = {MEASURED: _t(1), CONDITION: cond}
    assert s._load_data(data_same) is False

    # Only image changed should trigger update
    cond_changed_img = {**cond, IMAGE: "http://new.png"}
    data_img_change = {MEASURED: _t(2), CONDITION: cond_changed_img}
    assert s._load_data(data_img_change) is True
    assert s.entity_picture == "http://new.png"


def test_precipitation_forecast_nested() -> None:
    """Test nested precipitation forecast data parsing."""
    s = _sensor("precipitation_forecast_total")
    nested = {TIMEFRAME: 120, "total": 6.0, "average": 0.3}
    data = {MEASURED: _t(0), PRECIPITATION_FORECAST: nested}
    assert s._load_data(data) is True
    assert s.native_value == 6.0
    # The timeframe should be stored on the instance
    assert s._timeframe == 120
    # This branch does not populate extra attributes by design


@pytest.mark.parametrize("wind_key", [WINDSPEED, WINDGUST])
def test_wind_speed_branch_updates_and_changes_value(wind_key: str) -> None:
    """Test non-forecast windspeed and windgust conversion path."""
    s = _sensor(wind_key)

    # First call: should set native value
    d1 = {MEASURED: _t(0), wind_key: 3.0}
    assert s._load_data(d1) is True
    assert s.native_value is not None

    # Second call: new measurement, new value; expect update
    d2 = {MEASURED: _t(1), wind_key: 4.0}
    assert s._load_data(d2) is True
    assert s.native_value is not None


def test_visibility_branch_updates_and_changes_value() -> None:
    """Test visibility conversion path."""
    s = _sensor(VISIBILITY)

    d1 = {MEASURED: _t(0), VISIBILITY: 900}
    assert s._load_data(d1) is True
    assert s.native_value is not None

    d2 = {MEASURED: _t(1), VISIBILITY: 1000}
    assert s._load_data(d2) is True
    assert s.native_value is not None


def test_generic_sensor_sets_attributes_and_measured_label() -> None:
    """Test generic sensor branch and extra attribute population."""
    s = _sensor("temperature")
    d = {
        MEASURED: _t(0),
        "temperature": 21.5,
        ATTRIBUTION: "Buienradar",
        STATIONNAME: "Eindhoven",
    }
    assert s._load_data(d) is True
    assert s.native_value == 21.5

    attrs = s.extra_state_attributes
    # Basic attributes should exist
    assert attrs.get("attribution") == "Buienradar"
    assert attrs.get(STATIONNAME_LABEL) == "Eindhoven"
    # MEASURED_LABEL should be a formatted local time string
    assert isinstance(attrs.get(MEASURED_LABEL), str) and attrs.get(MEASURED_LABEL)

    # New measurement and value should trigger update
    d2 = {**d, MEASURED: _t(1), "temperature": 22.0}
    assert s._load_data(d2) is True
    assert s.native_value == 22.0


def test_windspeed_forecast_1d_simple_value() -> None:
    """Forecasted windspeed is converted to km/h on first set (5.0 -> 18.0)."""
    s = _sensor("windspeed_1d")
    d = {MEASURED: _t(0), FORECAST: [{"windspeed": 5.0}]}
    assert s._load_data(d) is True
    assert s.native_value == 18.0
