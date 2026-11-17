"""Post-install discovery and YAML import against a real Home Assistant."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers import instance_id
from homeassistant.loader import async_get_zeroconf
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.google_translator import CONFIG_SCHEMA
from custom_components.google_translator.accounts import account_unique_id
from custom_components.google_translator.api import GoogleWebClient
from custom_components.google_translator.const import (
    BACKEND_CLOUD,
    BACKEND_WEB,
    CONF_BACKEND,
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_DISCOVER_TRANSLATOR,
    CONF_MONTHLY_CHARACTER_LIMIT,
    CONF_YAML_MANAGED,
    DOMAIN,
)

from mocks import mock_cloud, mock_web

KEY = "yaml-test-key"


@pytest.fixture(autouse=True)
def answers(aioclient_mock):
    mock_web(aioclient_mock)
    mock_cloud(aioclient_mock)
    with patch.object(GoogleWebClient, "_spacing", 0):
        yield


async def discover(hass, uuid=None):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_ZEROCONF},
        data=SimpleNamespace(properties={"uuid": uuid or await instance_id.async_get(hass)}),
    )


async def import_yaml(hass, data):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data=data
    )
    await hass.async_block_till_done()
    return result


def accounts(hass):
    return [e for e in hass.config_entries.async_entries(DOMAIN) if e.source != config_entries.SOURCE_IGNORE]


# --- discovery through the instance's own mDNS advertisement ----------------------------------


async def test_manifest_registers_local_ha_discovery_and_only_suggests_setup(hass):
    matchers = await async_get_zeroconf(hass)
    assert any(item["domain"] == DOMAIN for item in matchers["_home-assistant._tcp.local."])
    with patch("custom_components.google_translator.config_flow.async_create_client") as client:
        result = await discover(hass)
        assert result["type"] == "form" and result["step_id"] == "discovery_confirm"
        assert not hass.config_entries.async_entries(DOMAIN)
        client.assert_not_called()
    duplicate = await discover(hass)
    assert duplicate["type"] == "abort" and duplicate["reason"] == "already_in_progress"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] == "menu" and result["menu_options"] == ["web", "cloud"]


async def test_other_servers_do_not_trigger_discovery(hass):
    result = await discover(hass, "another-ha-instance")
    assert result["type"] == "abort" and result["reason"] == "not_local_instance"


@pytest.mark.parametrize(
    "source,unique_id",
    [
        (config_entries.SOURCE_USER, "web"),
        (config_entries.SOURCE_USER, "cloud-account"),
        (config_entries.SOURCE_IGNORE, DOMAIN),
    ],
)
async def test_configured_and_ignored_accounts_are_not_suggested_again(hass, source, unique_id):
    MockConfigEntry(domain=DOMAIN, source=source, unique_id=unique_id).add_to_hass(hass)
    result = await discover(hass)
    assert result["type"] == "abort" and result["reason"] == "already_configured"


async def test_setting_up_an_account_clears_the_pending_suggestion(hass):
    suggestion = await discover(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "web"})
    await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DEFAULT_TARGET_LANGUAGE: "de"})
    await hass.async_block_till_done()
    assert suggestion["flow_id"] not in [flow["flow_id"] for flow in hass.config_entries.flow.async_progress()]


# --- YAML ---------------------------------------------------------------------------------------


def test_yaml_schema_validates_and_normalizes_the_account():
    config = CONFIG_SCHEMA(
        {
            DOMAIN: {
                CONF_API_KEY: f" {KEY} ",
                CONF_DEFAULT_TARGET_LANGUAGE: "pt_PT",
                CONF_MONTHLY_CHARACTER_LIMIT: "250000",
                CONF_CACHE_SIZE: 0,
                CONF_DISCOVER_TRANSLATOR: "off",
            },
            "other": {},
        }
    )
    assert config[DOMAIN] == {
        CONF_API_KEY: KEY,
        CONF_DEFAULT_TARGET_LANGUAGE: "pt-PT",
        CONF_MONTHLY_CHARACTER_LIMIT: 250000,
        CONF_CACHE_SIZE: 0,
        CONF_DISCOVER_TRANSLATOR: False,
    }


def test_a_bare_block_is_valid_and_means_the_keyless_account():
    assert CONFIG_SCHEMA({DOMAIN: None})[DOMAIN] == {}
    assert CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN] == {}
    assert CONFIG_SCHEMA({"other": {}}) == {"other": {}}


@pytest.mark.parametrize(
    "data",
    [{CONF_API_KEY: " "}, {CONF_MONTHLY_CHARACTER_LIMIT: -1}, {CONF_CACHE_SIZE: -1}, {"unknown": True}, "text"],
)
def test_invalid_yaml_is_rejected(data):
    with pytest.raises(vol.Invalid):
        CONFIG_SCHEMA({DOMAIN: data})


async def test_a_bare_block_sets_up_the_web_account_and_clears_the_suggestion(hass):
    hass.config.language = "de"
    suggestion = await discover(hass)
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})
    await hass.async_block_till_done()
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.source == config_entries.SOURCE_IMPORT
    assert entry.data == {CONF_BACKEND: BACKEND_WEB, CONF_YAML_MANAGED: True}
    assert entry.unique_id == account_unique_id(BACKEND_WEB)
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "de"
    assert entry.options[CONF_MONTHLY_CHARACTER_LIMIT] == 0
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert suggestion["flow_id"] not in [flow["flow_id"] for flow in hass.config_entries.flow.async_progress()]


async def test_a_key_sets_up_the_cloud_account_with_the_free_tier_as_budget(hass):
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {CONF_API_KEY: KEY, CONF_DEFAULT_TARGET_LANGUAGE: "FR"}})
    await hass.async_block_till_done()
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.data == {CONF_BACKEND: BACKEND_CLOUD, CONF_API_KEY: KEY, CONF_YAML_MANAGED: True}
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "fr"
    assert entry.options[CONF_MONTHLY_CHARACTER_LIMIT] == 500000
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_repeated_import_reuses_the_account_and_key_rotation_updates_it(hass):
    await import_yaml(hass, {CONF_API_KEY: KEY, CONF_DEFAULT_TARGET_LANGUAGE: "fr", CONF_CACHE_SIZE: 10})
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    result = await import_yaml(hass, {CONF_API_KEY: KEY})
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "fr" and entry.options[CONF_CACHE_SIZE] == 10
    await import_yaml(hass, {CONF_API_KEY: "rotated", CONF_CACHE_SIZE: 0})
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.data[CONF_API_KEY] == "rotated"
    assert entry.unique_id == account_unique_id(BACKEND_CLOUD, "rotated")
    assert entry.options[CONF_CACHE_SIZE] == 0
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_adding_or_dropping_the_key_switches_the_backend_and_its_budget(hass):
    await import_yaml(hass, {})
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.data[CONF_BACKEND] == BACKEND_WEB
    await import_yaml(hass, {CONF_API_KEY: KEY})
    assert entry.data[CONF_BACKEND] == BACKEND_CLOUD and entry.options[CONF_MONTHLY_CHARACTER_LIMIT] == 500000
    await import_yaml(hass, {})
    assert entry.data == {CONF_BACKEND: BACKEND_WEB, CONF_YAML_MANAGED: True}
    assert entry.options[CONF_MONTHLY_CHARACTER_LIMIT] == 0 and entry.title == "Google Translate"


async def test_a_limit_written_in_yaml_wins_over_the_default_of_the_backend(hass):
    await import_yaml(hass, {})
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    await import_yaml(hass, {CONF_API_KEY: KEY, CONF_MONTHLY_CHARACTER_LIMIT: 1234})
    assert entry.options[CONF_MONTHLY_CHARACTER_LIMIT] == 1234


async def test_yaml_adopts_the_same_ui_account_without_duplicates(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=account_unique_id(BACKEND_WEB),
        data={CONF_BACKEND: BACKEND_WEB},
        options={CONF_DEFAULT_TARGET_LANGUAGE: "fr"},
    )
    entry.add_to_hass(hass)
    result = await import_yaml(hass, {CONF_CACHE_SIZE: 0})
    assert result["type"] == "abort"
    assert hass.config_entries.async_entries(DOMAIN) == [entry]
    assert entry.data[CONF_YAML_MANAGED] and entry.options[CONF_DEFAULT_TARGET_LANGUAGE] == "fr"


async def test_yaml_does_not_take_over_another_account(hass):
    managed = MockConfigEntry(
        domain=DOMAIN, source=config_entries.SOURCE_IMPORT, unique_id=account_unique_id(BACKEND_WEB),
        data={CONF_BACKEND: BACKEND_WEB, CONF_YAML_MANAGED: True},
    )
    other = MockConfigEntry(
        domain=DOMAIN, unique_id=account_unique_id(BACKEND_CLOUD, "other"),
        data={CONF_BACKEND: BACKEND_CLOUD, CONF_API_KEY: "other"},
    )
    managed.add_to_hass(hass)
    other.add_to_hass(hass)
    result = await import_yaml(hass, {CONF_API_KEY: "other"})
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    assert managed.data[CONF_BACKEND] == BACKEND_WEB and other.data[CONF_API_KEY] == "other"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_invalid_yaml_given_to_the_flow_is_aborted(hass):
    result = await import_yaml(hass, {"unknown": True})
    assert result["type"] == "abort" and result["reason"] == "invalid_yaml"


async def test_startup_updates_a_stored_account_before_it_is_set_up(hass):
    """The new YAML values are used by the first setup, so no reload is needed."""
    entry = MockConfigEntry(
        domain=DOMAIN, source=config_entries.SOURCE_IMPORT, unique_id=account_unique_id(BACKEND_WEB),
        data={CONF_BACKEND: BACKEND_WEB, CONF_YAML_MANAGED: True}, options={CONF_CACHE_SIZE: 256},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {CONF_CACHE_SIZE: 5}})
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.data[DOMAIN][entry.entry_id].cache._max_size == 5
    assert hass.config_entries.async_entries(DOMAIN) == [entry]


async def test_an_ignored_suggestion_does_not_block_the_yaml_account(hass):
    MockConfigEntry(domain=DOMAIN, source=config_entries.SOURCE_IGNORE, unique_id=DOMAIN).add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: None})
    await hass.async_block_till_done()
    assert [e.data[CONF_BACKEND] for e in accounts(hass)] == [BACKEND_WEB]
