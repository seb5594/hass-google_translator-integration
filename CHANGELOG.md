# Changelog

## 2026.11.26

- **Security:** `google_translator.translate_structure` no longer overwrites existing YAML files. Before, `output_file` together with `overwrite: true` could replace files such as `configuration.yaml`, `secrets.yaml` or automations inside the configuration folder. YAML targets can only be created, and `overwrite` now applies to JSON files only. Writing a translated copy next to the original, such as `strings.de.json`, still works.

## 2026.19.11

- Use YYYY.DD.MM for the first daily build and .2, .3 for subsequent builds.
- Publish release tags without the v prefix.


## 2026.11.17.1

- Published under the MIT license.
- First release of Google Translator for Home Assistant 2023.7 and newer.
- Two ways to reach Google Translate: the keyless web endpoint that translate.google.com uses (free,
  unofficial) or the official Cloud Translation API with an API key.
- Services `translate_text`, `translate_structure`, `get_languages` and `get_usage`, all of which
  return their result to the caller. They answer in the same shape as DeepL Translator, so callers
  such as Custom Integration Translator can use either.
- Google reports no usage figures, so characters are counted per month and kept across restarts.
  A monthly character limit (500,000 for the Cloud API, the size of its free tier) refuses a request
  that would exceed it before anything is sent. Usage sensors show the count and what is left.
- Requests are checked before anything is sent: language, text size and budget. This matters most
  for the keyless endpoint, which answers an unknown language with the unchanged text.
- `translate_structure` translates only the text values of JSON and YAML data and keeps the layout of
  files. Placeholders such as `{name}` and `%s` are protected and verified; administrators only.
- Setup suggestion under *Devices & services* after installation, from the mDNS advertisement of
  the Home Assistant instance itself, and an optional account in `configuration.yaml`.
- Custom Integration Translator 2026.11.17.1 or newer is offered after installation and can use
  this account next to or instead of DeepL.
- Reauthentication when Google rejects the API key, diagnostics without the key, English and German
  translations.
