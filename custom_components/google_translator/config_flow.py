"""Config flow for the Google Translator integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import (
    SOURCE_IGNORE,
    SOURCE_ZEROCONF,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import callback
from homeassistant.helpers import instance_id
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

try:
    from homeassistant.config_entries import ConfigFlowResult
except ImportError:  # Home Assistant older than 2024.4
    from homeassistant.data_entry_flow import FlowResult as ConfigFlowResult

from .accounts import account_title, account_unique_id
from .api import GoogleAuthError, GoogleError, GoogleQuotaError
from .const import (
    BACKEND_CLOUD,
    BACKEND_WEB,
    CONF_BACKEND,
    CONF_CACHE_SIZE,
    CONF_DEFAULT_TARGET_LANGUAGE,
    CONF_DISCOVER_TRANSLATOR,
    CONF_MONTHLY_CHARACTER_LIMIT,
    DEFAULT_CACHE_SIZE,
    DOMAIN,
    MAX_CACHE_SIZE,
    MAX_MONTHLY_CHARACTER_LIMIT,
)
from .data import async_create_client
from .languages import COMMON_LANGUAGES, normalize_language, target_from_home_assistant_language
from .yaml_config import (
    YAML_ACCOUNT_SCHEMA,
    YamlConflict,
    apply_to_existing_account,
    backend_of,
    default_monthly_limit,
    entry_data,
    entry_options,
)

if TYPE_CHECKING:
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

_LOGGER = logging.getLogger(__name__)


def _language_selector() -> SelectSelector:
    """A drop-down of the common targets that still accepts any code Google lists."""
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=code, label=f"{name} ({code})")
                for code, name in COMMON_LANGUAGES.items()
            ],
            mode=SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


def _limit_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=MAX_MONTHLY_CHARACTER_LIMIT,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="characters",
        )
    )


def _cache_selector() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=0, max=MAX_CACHE_SIZE, step=1, mode=NumberSelectorMode.BOX)
    )


def _api_key_schema(suggested_key: str | None = None) -> dict[Any, Any]:
    description = {"suggested_value": suggested_key} if suggested_key else None
    return {
        vol.Required(CONF_API_KEY, description=description): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }


class GoogleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Google Translate without a key, or with a Cloud Translation API key."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Offer the options of an existing entry."""
        return GoogleOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user choose how to reach Google."""
        return self.async_show_menu(step_id="user", menu_options=[BACKEND_WEB, BACKEND_CLOUD])

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Suggest setup when Home Assistant sees this installation's own mDNS service."""
        if discovery_info.properties.get("uuid") != await instance_id.async_get(self.hass):
            return self.async_abort(reason="not_local_instance")
        if any(entry.source != SOURCE_IGNORE for entry in self._async_current_entries()):
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        self.context["title_placeholders"] = {"name": "Google Translator"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Wait for the user before contacting Google."""
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(step_id="discovery_confirm", data_schema=vol.Schema({}))

    @callback
    def _async_clear_discovery_flows(self) -> None:
        """A configured account makes other setup suggestions unnecessary."""
        for flow in self.hass.config_entries.flow.async_progress_by_handler(DOMAIN):
            if flow["flow_id"] != self.flow_id and flow["context"].get("source") == SOURCE_ZEROCONF:
                self.hass.config_entries.flow.async_abort(flow["flow_id"])

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Create the YAML-managed account, or update it if it exists.

        Nothing is sent to Google here: entry setup retries connection failures and starts
        reauthentication for a rejected key, so YAML can be imported while Google is unreachable.
        """
        try:
            account = YAML_ACCOUNT_SCHEMA(user_input)
        except vol.Invalid:
            return self.async_abort(reason="invalid_yaml")
        try:
            known = apply_to_existing_account(self.hass, account)
        except YamlConflict:
            return self.async_abort(reason="already_configured")
        self._async_clear_discovery_flows()
        if known:
            return self.async_abort(reason="already_configured")

        backend = backend_of(account)
        await self.async_set_unique_id(account_unique_id(backend, account.get(CONF_API_KEY)))
        options = entry_options(account)
        options.setdefault(
            CONF_DEFAULT_TARGET_LANGUAGE,
            target_from_home_assistant_language(self.hass.config.language),
        )
        options.setdefault(CONF_MONTHLY_CHARACTER_LIMIT, default_monthly_limit(backend))
        return self.async_create_entry(
            title=account_title(backend), data=entry_data(account), options=options
        )

    async def _async_check(self, backend: str, api_key: str | None = None) -> str | None:
        """Return an error key when translating does not work with these settings."""
        try:
            client = await async_create_client(self.hass, backend, api_key)
            await client.async_check()
        except GoogleAuthError:
            return "invalid_auth"
        except GoogleQuotaError:
            return "rate_limited"
        except GoogleError:
            return "cannot_connect"
        except Exception:  # noqa: BLE001 - the form must stay usable whatever happens
            _LOGGER.exception("Unexpected error while checking Google Translate")
            return "unknown"
        return None

    def _server_language(self) -> str:
        return target_from_home_assistant_language(self.hass.config.language)

    async def async_step_web(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up the keyless web endpoint."""
        await self.async_set_unique_id(account_unique_id(BACKEND_WEB))
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := await self._async_check(BACKEND_WEB):
                errors["base"] = error
            else:
                self._async_clear_discovery_flows()
                return self.async_create_entry(
                    title=account_title(BACKEND_WEB),
                    data={CONF_BACKEND: BACKEND_WEB},
                    options={
                        CONF_DEFAULT_TARGET_LANGUAGE: normalize_language(
                            user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                        ),
                        CONF_MONTHLY_CHARACTER_LIMIT: default_monthly_limit(BACKEND_WEB),
                    },
                )
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE, default=self._server_language()
                ): _language_selector()
            }
        )
        return self.async_show_form(step_id=BACKEND_WEB, data_schema=schema, errors=errors)

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Set up the Cloud Translation API with an API key."""
        errors: dict[str, str] = {}
        suggested_key = None
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            suggested_key = api_key
            await self.async_set_unique_id(account_unique_id(BACKEND_CLOUD, api_key))
            self._abort_if_unique_id_configured()
            if error := await self._async_check(BACKEND_CLOUD, api_key):
                errors["base"] = error
            else:
                self._async_clear_discovery_flows()
                return self.async_create_entry(
                    title=account_title(BACKEND_CLOUD),
                    data={CONF_BACKEND: BACKEND_CLOUD, CONF_API_KEY: api_key},
                    options={
                        CONF_DEFAULT_TARGET_LANGUAGE: normalize_language(
                            user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                        ),
                        CONF_MONTHLY_CHARACTER_LIMIT: int(user_input[CONF_MONTHLY_CHARACTER_LIMIT]),
                    },
                )
        schema = vol.Schema(
            {
                **_api_key_schema(suggested_key),
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE, default=self._server_language()
                ): _language_selector(),
                vol.Required(
                    CONF_MONTHLY_CHARACTER_LIMIT, default=default_monthly_limit(BACKEND_CLOUD)
                ): _limit_selector(),
            }
        )
        return self.async_show_form(step_id=BACKEND_CLOUD, data_schema=schema, errors=errors)

    async def async_step_reauth(self, entry_data: Any) -> ConfigFlowResult:
        """Start when Google rejects the stored key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new key."""
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if error := await self._async_check(BACKEND_CLOUD, api_key):
                errors["base"] = error
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_API_KEY: api_key},
                    unique_id=account_unique_id(BACKEND_CLOUD, api_key),
                )
                # A loaded entry reloads through its update listener; the others need a nudge.
                if entry.state is not ConfigEntryState.LOADED:
                    await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(_api_key_schema()),
            description_placeholders={"account": entry.title},
            errors=errors,
        )


class GoogleOptionsFlow(OptionsFlow):
    """Change the defaults of an account."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the options."""
        # The entry id is the flow's handler in every Home Assistant version.
        entry = self.hass.config_entries.async_get_entry(self.handler)
        options = entry.options
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    **options,
                    CONF_DISCOVER_TRANSLATOR: user_input[CONF_DISCOVER_TRANSLATOR],
                    CONF_DEFAULT_TARGET_LANGUAGE: normalize_language(
                        user_input[CONF_DEFAULT_TARGET_LANGUAGE]
                    ),
                    CONF_MONTHLY_CHARACTER_LIMIT: int(user_input[CONF_MONTHLY_CHARACTER_LIMIT]),
                    CONF_CACHE_SIZE: int(user_input[CONF_CACHE_SIZE]),
                },
            )
        backend = entry.data.get(CONF_BACKEND, BACKEND_WEB)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DISCOVER_TRANSLATOR, default=options.get(CONF_DISCOVER_TRANSLATOR, True)
                ): bool,
                vol.Required(
                    CONF_DEFAULT_TARGET_LANGUAGE,
                    default=options.get(
                        CONF_DEFAULT_TARGET_LANGUAGE,
                        target_from_home_assistant_language(self.hass.config.language),
                    ),
                ): _language_selector(),
                vol.Required(
                    CONF_MONTHLY_CHARACTER_LIMIT,
                    default=options.get(CONF_MONTHLY_CHARACTER_LIMIT, default_monthly_limit(backend)),
                ): _limit_selector(),
                vol.Required(
                    CONF_CACHE_SIZE, default=options.get(CONF_CACHE_SIZE, DEFAULT_CACHE_SIZE)
                ): _cache_selector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
