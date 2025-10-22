"""Test async_disable_proactive_mode is synchronous."""

from unittest.mock import Mock

from homeassistant.core import HomeAssistant

from .test_common import get_default_config


def test_disable_proactive_mode_is_synchronous(hass: HomeAssistant) -> None:
    """Test disabling proactive mode is a synchronous callback method."""
    config = get_default_config(hass)

    # Set up a mock unsubscribe function
    mock_unsub = Mock()
    config._unsub_proactive_report = mock_unsub

    # Call without await - this should work since it's now synchronous
    config.async_disable_proactive_mode()

    # Verify the unsubscribe function was called
    mock_unsub.assert_called_once()

    # Verify the internal state was cleared
    assert config._unsub_proactive_report is None


def test_disable_proactive_mode_when_none(hass: HomeAssistant) -> None:
    """Test disabling proactive mode when no subscription exists."""
    config = get_default_config(hass)

    # Ensure no subscription exists
    config._unsub_proactive_report = None

    # This should not raise an error
    config.async_disable_proactive_mode()

    # State should remain None
    assert config._unsub_proactive_report is None
