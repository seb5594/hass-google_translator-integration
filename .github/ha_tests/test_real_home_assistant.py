"""The integration inside a genuine Home Assistant core.

They need Home Assistant and pytest-homeassistant-custom-component. The shared engine installs
both for every release the Compatibility workflow lists. Google is never contacted: every
request is answered by a mock.
"""

import json
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import ConfigEntryState  # noqa: E402
from homeassistant.const import CONF_API_KEY  # noqa: E402
from homeassistant.core import Context  # noqa: E402
from homeassistant.exceptions import HomeAssistantError, Unauthorized  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse  # noqa: E402

from custom_components.google_translator.accounts import account_unique_id  # noqa: E402
from custom_components.google_translator.api import GoogleWebClient  # noqa: E402
from custom_components.google_translator.const import (  # noqa: E402
    BACKEND_CLOUD,
    BACKEND_WEB,
    CONF_BACKEND,
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_MONTHLY_CHARACTER_LIMIT,
    DOMAIN,
)

from mocks import CLOUD, CLOUD_LANGUAGES, WEB, WEB_LANGUAGES, mock_cloud, mock_web, translate_calls  # noqa: E402

CLOUD_KEY = "test-key"


@pytest.fixture(autouse=True)
def no_waiting():
    """Requests are spaced out and retried with a delay; neither should slow the tests."""
    with patch.object(GoogleWebClient, "_spacing", 0), patch(
        "custom_components.google_translator.api.asyncio.sleep"
    ):
        yield


async def add_account(hass, backend=BACKEND_WEB, limit=0, **options):
    data = {CONF_BACKEND: backend}
    if backend == BACKEND_CLOUD:
        data[CONF_API_KEY] = CLOUD_KEY
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Google Translate",
        unique_id=account_unique_id(backend, data.get(CONF_API_KEY)),
        data=data,
        options={CONF_DEFAULT_TARGET_LANGUAGE: "de", CONF_MONTHLY_CHARACTER_LIMIT: limit, **options},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def call(hass, service, data, **kwargs):
    return await hass.services.async_call(DOMAIN, service, data, blocking=True, return_response=True, **kwargs)


# --- setting up -------------------------------------------------------------------------------


async def test_web_flow_creates_the_account_and_refuses_a_second(hass, aioclient_mock):
    mock_web(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu" and result["menu_options"] == ["web", "cloud"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "web"})
    assert result["type"] == "form" and result["step_id"] == "web"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DEFAULT_TARGET_LANGUAGE: "FR"})
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_BACKEND: BACKEND_WEB}
    assert result["options"][CONF_DEFAULT_TARGET_LANGUAGE] == "fr"
    assert result["options"][CONF_MONTHLY_CHARACTER_LIMIT] == 0
    await hass.async_block_till_done()
    again = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    again = await hass.config_entries.flow.async_configure(again["flow_id"], {"next_step_id": "web"})
    assert again["type"] == "abort" and again["reason"] == "already_configured"


@pytest.mark.parametrize(
    "response,error",
    [({"status": 429, "text": "<html>captcha</html>"}, "rate_limited"), ({"status": 500, "json": {}}, "cannot_connect")],
)
async def test_web_flow_explains_why_google_cannot_be_used(hass, aioclient_mock, response, error):
    aioclient_mock.post(f"{WEB}/t", **response)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "web"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_DEFAULT_TARGET_LANGUAGE: "de"})
    assert result["type"] == "form" and result["errors"] == {"base": error}


async def test_cloud_flow_sends_the_key_in_a_header_and_budgets_the_free_tier(hass, aioclient_mock):
    mock_cloud(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: f" {CLOUD_KEY} ", CONF_DEFAULT_TARGET_LANGUAGE: "de", CONF_MONTHLY_CHARACTER_LIMIT: 500000},
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_BACKEND: BACKEND_CLOUD, CONF_API_KEY: CLOUD_KEY}
    assert result["options"][CONF_MONTHLY_CHARACTER_LIMIT] == 500000
    method, url, body, headers = translate_calls(aioclient_mock, "cloud")[0]
    assert headers["X-goog-api-key"] == CLOUD_KEY and "key=" not in str(url)
    assert body == {"q": ["Hello"], "target": "de", "format": "text", "source": "en"}


async def test_cloud_flow_rejects_a_bad_key(hass, aioclient_mock):
    error = {"error": {"code": 400, "message": "API key not valid.", "errors": [{"reason": "badRequest"}], "details": [{"reason": "API_KEY_INVALID"}]}}
    aioclient_mock.post(CLOUD, status=400, json=error)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "cloud"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "bad", CONF_DEFAULT_TARGET_LANGUAGE: "de", CONF_MONTHLY_CHARACTER_LIMIT: 0}
    )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_entry_loads_and_unloads(hass, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.services.has_service(DOMAIN, "translate_text")
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED and entry.entry_id not in hass.data[DOMAIN]


async def test_a_rejected_cloud_key_starts_reauthentication(hass, aioclient_mock):
    aioclient_mock.get(f"{CLOUD}/languages", status=403, json={"error": {"code": 403, "message": "Forbidden", "errors": [{"reason": "forbidden"}]}})
    entry = await add_account(hass, BACKEND_CLOUD)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_reauthentication_replaces_the_key_and_reloads(hass, aioclient_mock):
    aioclient_mock.get(f"{CLOUD}/languages", status=403, json={"error": {"message": "Forbidden"}})
    entry = await add_account(hass, BACKEND_CLOUD)
    aioclient_mock.clear_requests()
    mock_cloud(aioclient_mock)
    flow = next(f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth")
    result = await hass.config_entries.flow.async_configure(flow["flow_id"], {CONF_API_KEY: "new-key"})
    await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_KEY] == "new-key" and entry.state is ConfigEntryState.LOADED


async def test_options_flow_changes_the_defaults(hass, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"discover_translator": False, CONF_DEFAULT_TARGET_LANGUAGE: "FR", CONF_MONTHLY_CHARACTER_LIMIT: 1000, CONF_CACHE_SIZE: 0},
    )
    await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert entry.options == {
        "discover_translator": False, CONF_DEFAULT_TARGET_LANGUAGE: "fr", CONF_MONTHLY_CHARACTER_LIMIT: 1000, CONF_CACHE_SIZE: 0,
    }
    assert hass.data[DOMAIN][entry.entry_id].default_target_language == "fr"


# --- translating ------------------------------------------------------------------------------


async def test_translate_text_through_the_web_endpoint(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    result = await call(hass, "translate_text", {"text": ["Good morning", "Good night"], "source_language": "EN"})
    assert result["text"] == "DE Good morning" and result["target_language"] == "de"
    assert [item["text"] for item in result["translations"]] == ["DE Good morning", "DE Good night"]
    (_, url, body, _), = translate_calls(aioclient_mock)
    assert dict(url.query) == {"client": "gtx", "format": "text", "sl": "en", "tl": "de"}
    assert body == [("q", "Good morning"), ("q", "Good night")]


async def test_target_language_spellings_are_matched_to_the_list_google_offers(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    for typed, sent in {"zh_hans": "zh-CN", "HE": "iw", "FR": "fr"}.items():
        aioclient_mock.mock_calls.clear()
        result = await call(hass, "translate_text", {"text": typed, "target_language": typed})
        assert result["target_language"] == sent
        assert translate_calls(aioclient_mock)[0][1].query["tl"] == sent


async def test_repeated_texts_come_from_the_cache_and_cost_nothing(hass, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass)
    await call(hass, "translate_text", {"text": ["Hello", "Hello", "  "]})
    result = await call(hass, "translate_text", {"text": ["Hello", "  "]})
    assert [item["text"] for item in result["translations"]] == ["DE Hello", "  "]
    assert len(translate_calls(aioclient_mock)) == 1
    assert hass.data[DOMAIN][entry.entry_id].usage.usage.character_count == len("Hello")


async def test_many_texts_are_split_into_requests_in_their_original_order(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    texts = [f"text {index}" for index in range(60)]
    result = await call(hass, "translate_text", {"text": texts})
    assert [item["text"] for item in result["translations"]] == [f"DE {text}" for text in texts]
    assert [len([k for k, _ in c[2]]) for c in translate_calls(aioclient_mock)] == [25, 25, 10]


async def test_translate_text_through_the_cloud_api(hass, aioclient_mock):
    mock_cloud(aioclient_mock)
    await add_account(hass, BACKEND_CLOUD, limit=500000)
    result = await call(hass, "translate_text", {"text": "Hello", "source_language": "en"})
    assert result["translations"] == [{"text": "DE Hello", "detected_source_language": "en"}]
    (_, _, body, headers), = translate_calls(aioclient_mock, "cloud")
    assert body == {"q": ["Hello"], "target": "de", "format": "text", "source": "en"}
    assert headers["X-goog-api-key"] == CLOUD_KEY


async def test_an_unknown_language_is_refused_before_anything_is_sent(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    with pytest.raises(HomeAssistantError, match="Nothing was sent"):
        await call(hass, "translate_text", {"text": "Hello", "target_language": "dd"})
    assert not translate_calls(aioclient_mock)


async def test_a_request_beyond_the_monthly_budget_is_refused_completely(hass, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass, limit=12)
    await call(hass, "translate_text", {"text": "Hello"})
    with pytest.raises(HomeAssistantError, match="monthly character budget"):
        await call(hass, "translate_text", {"text": ["Good", "morning"]})
    assert len(translate_calls(aioclient_mock)) == 1
    assert hass.data[DOMAIN][entry.entry_id].usage.usage.characters_remaining == 7


async def test_a_text_too_long_for_one_request_is_refused(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    with pytest.raises(HomeAssistantError, match="Split it into smaller texts"):
        await call(hass, "translate_text", {"text": "x" * 5001})
    assert not translate_calls(aioclient_mock)


async def test_google_limiting_the_web_endpoint_is_explained(hass, aioclient_mock):
    aioclient_mock.get(f"{WEB}/l", json=WEB_LANGUAGES)
    aioclient_mock.post(f"{WEB}/t", status=429, text="<html>unusual traffic</html>")
    await add_account(hass)
    with pytest.raises(HomeAssistantError, match="limiting requests"):
        await call(hass, "translate_text", {"text": "Hello"})
    assert len(translate_calls(aioclient_mock)) == 3  # the retries before giving up


async def test_a_temporary_failure_is_retried(hass, aioclient_mock):
    attempts = []

    async def flaky(method, url, data):
        attempts.append(1)
        if len(attempts) == 1:
            return AiohttpClientMockResponse(method, url, status=503, text="try later")
        return AiohttpClientMockResponse(method, url, json=["Hallo"])

    aioclient_mock.get(f"{WEB}/l", json=WEB_LANGUAGES)
    aioclient_mock.post(f"{WEB}/t", side_effect=flaky)
    await add_account(hass)
    assert (await call(hass, "translate_text", {"text": "Hello"}))["text"] == "Hallo"


async def test_both_shapes_of_the_web_answer_are_understood(hass, aioclient_mock):
    aioclient_mock.get(f"{WEB}/l", json=WEB_LANGUAGES)
    aioclient_mock.post(f"{WEB}/t", json=[["Hallo", "en"], ["Welt", "en"]])
    await add_account(hass)
    result = await call(hass, "translate_text", {"text": ["Hello", "World"]})
    assert [i["detected_source_language"] for i in result["translations"]] == ["en", "en"]


async def test_an_answer_with_the_wrong_number_of_texts_is_an_error(hass, aioclient_mock):
    aioclient_mock.get(f"{WEB}/l", json=WEB_LANGUAGES)
    aioclient_mock.post(f"{WEB}/t", json=["only one"])
    await add_account(hass)
    with pytest.raises(HomeAssistantError, match="unexpected number"):
        await call(hass, "translate_text", {"text": ["a", "b"]})


async def test_cloud_quota_errors_are_not_mistaken_for_a_bad_key(hass, aioclient_mock):
    mock_cloud(aioclient_mock)
    entry = await add_account(hass, BACKEND_CLOUD)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{CLOUD}/languages", json=CLOUD_LANGUAGES)
    aioclient_mock.post(CLOUD, status=403, json={"error": {"code": 403, "message": "Daily Limit Exceeded", "errors": [{"reason": "dailyLimitExceeded"}]}})
    with pytest.raises(HomeAssistantError, match="Daily Limit Exceeded"):
        await call(hass, "translate_text", {"text": "Hello"})
    assert entry.state is ConfigEntryState.LOADED
    assert not [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]


# --- usage ------------------------------------------------------------------------------------


async def test_usage_is_counted_reported_and_shown_by_sensors(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass, limit=1000)
    await call(hass, "translate_text", {"text": "Hello world"})
    usage = await call(hass, "get_usage", {"refresh": True})
    assert usage["available"] and usage["estimated"] and not usage["unlimited"]
    assert (usage["character_count"], usage["character_limit"], usage["characters_remaining"]) == (11, 1000, 989)
    assert usage["refreshed"] is True
    states = {state.entity_id: state.state for state in hass.states.async_all("sensor")}
    assert states["sensor.google_translate_characters_used_this_month"] == "11"
    assert states["sensor.google_translate_characters_remaining"] == "989"
    assert float(states["sensor.google_translate_budget_used"]) == 1.1


async def test_without_a_budget_usage_is_unlimited(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    usage = await call(hass, "get_usage", {})
    assert usage["unlimited"] and usage["character_limit"] is None and usage["characters_remaining"] is None


async def test_the_count_is_saved_and_restored(hass, hass_storage, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass, limit=1000)
    await call(hass, "translate_text", {"text": "Hello"})
    runtime = hass.data[DOMAIN][entry.entry_id]
    key = f"{DOMAIN}.{entry.entry_id}"
    assert runtime.usage.usage.character_count == 5
    await hass.config_entries.async_unload(entry.entry_id)
    assert hass_storage[key]["data"]["characters"] == 5
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.data[DOMAIN][entry.entry_id].usage.usage.character_count == 5


async def test_removing_the_account_forgets_its_count(hass, hass_storage, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass)
    await call(hass, "translate_text", {"text": "Hello"})
    await hass.config_entries.async_unload(entry.entry_id)
    key = f"{DOMAIN}.{entry.entry_id}"
    assert key in hass_storage
    await hass.config_entries.async_remove(entry.entry_id)
    assert key not in hass_storage


async def test_get_languages_lists_what_google_offers(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    result = await call(hass, "get_languages", {})
    assert {item["code"] for item in result["languages"]} == set(WEB_LANGUAGES["tl"])


async def test_several_accounts_need_a_choice(hass, aioclient_mock):
    mock_web(aioclient_mock)
    mock_cloud(aioclient_mock)
    web = await add_account(hass)
    await add_account(hass, BACKEND_CLOUD)
    with pytest.raises(HomeAssistantError, match="choose one"):
        await call(hass, "translate_text", {"text": "Hello"})
    assert (await call(hass, "translate_text", {"text": "Hello", "config_entry_id": web.entry_id}))["text"] == "DE Hello"


# --- structured data --------------------------------------------------------------------------


async def test_translate_structure_translates_only_text_values(hass, aioclient_mock):
    mock_web(aioclient_mock)
    await add_account(hass)
    data = {"title": "Open the door", "icon": "mdi:door", "count": 3, "items": ["Close", "https://example.com"]}
    result = await call(hass, "translate_structure", {"data": data})
    assert result["data"] == {"title": "DE Open the door", "icon": "mdi:door", "count": 3, "items": ["DE Close", "https://example.com"]}
    assert result["translated_strings"] == 2 and result["skipped_strings"] == 2


async def test_translate_structure_shields_placeholders(hass, aioclient_mock):
    mock_web(aioclient_mock, translate=lambda text: text.replace("Hello", "Hallo"))
    await add_account(hass)
    result = await call(hass, "translate_structure", {"data": {"msg": "Hello {name}, you have %s alerts"}})
    assert result["data"] == {"msg": "Hallo {name}, you have %s alerts"}
    sent = translate_calls(aioclient_mock)[0][2][0][1]
    assert "{name}" not in sent and "%s" not in sent


async def test_a_translation_that_loses_a_placeholder_is_reported(hass, aioclient_mock):
    mock_web(aioclient_mock, translate=lambda text: "Hallo")
    await add_account(hass)
    with pytest.raises(HomeAssistantError, match="placeholder"):
        await call(hass, "translate_structure", {"data": {"msg": "Hello {name}"}})


async def test_translate_structure_keeps_the_layout_of_a_json_file(hass, aioclient_mock, tmp_path):
    mock_web(aioclient_mock)
    await add_account(hass)
    hass.config.allowlist_external_dirs = {str(tmp_path)}
    source = tmp_path / "en.json"
    source.write_text('{\n    "title":   "Hello",\n    "id": "light_one"\n}\n', encoding="utf-8")
    result = await call(hass, "translate_structure", {"input_file": str(source)})
    target = tmp_path / "en.de.json"
    assert result["output_file"] == str(target)
    assert target.read_text(encoding="utf-8") == '{\n    "title":   "DE Hello",\n    "id": "light_one"\n}\n'


async def test_dry_run_sends_and_counts_nothing(hass, aioclient_mock):
    mock_web(aioclient_mock)
    entry = await add_account(hass, limit=100)
    result = await call(hass, "translate_structure", {"data": {"a": "Hello"}, "dry_run": True})
    assert result["dry_run"] and result["characters"] == 5 and result["characters_remaining"] == 100
    assert not translate_calls(aioclient_mock)
    assert hass.data[DOMAIN][entry.entry_id].usage.usage.character_count == 0


async def test_file_services_refuse_users_who_are_not_administrators(hass, aioclient_mock, hass_read_only_user):
    mock_web(aioclient_mock)
    await add_account(hass)
    with pytest.raises(Unauthorized):
        await call(hass, "translate_structure", {"data": {"a": "Hello"}}, context=Context(user_id=hass_read_only_user.id))
    assert not translate_calls(aioclient_mock)


async def test_administrators_and_other_services_stay_open(hass, aioclient_mock, hass_admin_user, hass_read_only_user):
    mock_web(aioclient_mock)
    await add_account(hass)
    await call(hass, "translate_structure", {"data": {"a": "Hello"}}, context=Context(user_id=hass_admin_user.id))
    await call(hass, "translate_text", {"text": "Hello"}, context=Context(user_id=hass_read_only_user.id))


# --- diagnostics ------------------------------------------------------------------------------


async def test_diagnostics_hide_the_api_key(hass, aioclient_mock):
    from custom_components.google_translator.diagnostics import async_get_config_entry_diagnostics

    mock_cloud(aioclient_mock)
    entry = await add_account(hass, BACKEND_CLOUD, limit=500000)
    report = await async_get_config_entry_diagnostics(hass, entry)
    assert CLOUD_KEY not in json.dumps(report)
    assert report["capabilities"]["billed"] is True and report["usage"]["character_limit"] == 500000
