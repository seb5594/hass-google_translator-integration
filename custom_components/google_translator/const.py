"""Constants for the Google Translator integration."""

from __future__ import annotations

DOMAIN = "google_translator"

# Config entry data
CONF_BACKEND = "backend"
CONF_YAML_MANAGED = "yaml_managed"

# Config entry options
CONF_DEFAULT_TARGET_LANGUAGE = "default_target_language"
CONF_MONTHLY_CHARACTER_LIMIT = "monthly_character_limit"
CONF_CACHE_SIZE = "cache_size"
CONF_DISCOVER_TRANSLATOR = "discover_translator"

# The two ways to reach Google Translate
BACKEND_WEB = "web"
BACKEND_CLOUD = "cloud"
BACKENDS = (BACKEND_WEB, BACKEND_CLOUD)

# Endpoints
WEB_URL = "https://translate.googleapis.com/translate_a"
CLOUD_URL = "https://translation.googleapis.com/language/translate/v2"

# Requests
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 30
LANGUAGES_CACHE_SECONDS = 24 * 3600

# Limits per request. The web endpoint is not documented, so its limits are deliberately modest;
# the Cloud API allows 128 texts and 30,000 characters per request.
WEB_MAX_TEXTS_PER_REQUEST = 25
WEB_MAX_REQUEST_CHARACTERS = 5000
WEB_REQUEST_SPACING = 0.4
CLOUD_MAX_TEXTS_PER_REQUEST = 100
CLOUD_MAX_REQUEST_CHARACTERS = 20_000
CLOUD_MAX_TEXT_CHARACTERS = 30_000

# Google publishes no usage figures, so the integration counts characters itself. The Cloud API
# is free up to this many characters per month, which is why it is the default budget there.
CLOUD_FREE_MONTHLY_CHARACTERS = 500_000
MAX_MONTHLY_CHARACTER_LIMIT = 1_000_000_000

# Translation cache (number of entries, 0 disables it)
DEFAULT_CACHE_SIZE = 256
MAX_CACHE_SIZE = 5000
CACHE_MAX_TEXT_LENGTH = 5000

# Service names
SERVICE_TRANSLATE_TEXT = "translate_text"
SERVICE_TRANSLATE_STRUCTURE = "translate_structure"
SERVICE_GET_LANGUAGES = "get_languages"
SERVICE_GET_USAGE = "get_usage"

# Service fields
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_TEXT = "text"
ATTR_TARGET_LANGUAGE = "target_language"
ATTR_SOURCE_LANGUAGE = "source_language"
ATTR_INPUT_FILE = "input_file"
ATTR_OUTPUT_FILE = "output_file"
ATTR_OVERWRITE = "overwrite"
ATTR_LANGUAGE_TYPE = "type"
ATTR_DATA = "data"
ATTR_FORMAT = "format"
ATTR_ONLY_KEYS = "only_keys"
ATTR_IGNORE_KEYS = "ignore_keys"
ATTR_SKIP_TECHNICAL_VALUES = "skip_technical_values"
ATTR_PROTECT_PLACEHOLDERS = "protect_placeholders"
ATTR_DRY_RUN = "dry_run"
ATTR_REFRESH = "refresh"

LANGUAGE_TYPES = ("target", "source")
STRUCTURE_FORMATS = ("auto", "json", "yaml")
STRUCTURE_SUFFIXES = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024
