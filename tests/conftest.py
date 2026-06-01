"""Pytest configuration for RideRadar."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations for Home Assistant config flow tests."""
    yield


def pytest_configure(config):
    """Register custom markers used by Home Assistant test helpers."""
    config.addinivalue_line("markers", "enable_socket: allow sockets in a test")
