"""Shared fixtures of the tests against a real Home Assistant core."""
import pytest

from custom_components.google_translator.const import DOMAIN


@pytest.fixture(autouse=True)
async def unload_accounts(hass):
    """Unload what a test set up, so its monthly timer does not outlive the test."""
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
