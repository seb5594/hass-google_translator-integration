<!-- header:begin (generated from project metadata) -->
<h1 align="center">Google Translator</h1>

<p align="center">
  <img src="https://raw.githubusercontent.com/seb5594/hass-google_translator-integration/main/custom_components/google_translator/brand/icon@2x.png" alt="Google Translator" width="160" height="160">
</p>

---

<p align="center">
  <a href="https://paypal.me/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=PayPal&amp;color=0070BA&amp;logo=paypal&amp;logoColor=white&amp;style=for-the-badge" alt="PayPal" height="40"></a>
  <a href="https://buymeacoffee.com/seb5594"><img src="https://img.shields.io/static/v1?label=Support&amp;message=Buy%20Me%20a%20Coffee&amp;color=FFDD00&amp;logo=buy-me-a-coffee&amp;logoColor=black&amp;style=for-the-badge" alt="Buy Me a Coffee" height="40"></a><br>
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=seb5594&amp;repository=hass-google_translator-integration&amp;category=integration"><img src="https://img.shields.io/static/v1?label=HACS&amp;message=Add%20integration&amp;color=41BDF5&amp;logo=homeassistantcommunitystore&amp;logoColor=white&amp;style=for-the-badge" alt="HACS" height="28"></a>
  <a href="https://github.com/seb5594/hass-google_translator-integration/actions/workflows/compat.yml"><img src="https://img.shields.io/static/v1?label=home%20assistant&amp;message=%E2%89%A5%202023.7.0&amp;color=1877A5&amp;style=for-the-badge" alt="home assistant" height="28"></a>
  <a href="https://github.com/seb5594/hass-google_translator-integration/releases"><img src="https://img.shields.io/static/v1?label=version&amp;message=2026.11.17.1&amp;color=1877A5&amp;style=for-the-badge" alt="version" height="28"></a><br>
  <a href="https://github.com/seb5594/hass-google_translator-integration/issues"><img src="https://img.shields.io/github/issues/seb5594/hass-google_translator-integration?label=issues&amp;style=flat" alt="issues" height="20"></a>
  <a href="https://github.com/seb5594/hass-google_translator-integration/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/seb5594/hass-google_translator-integration/ci.yml?branch=main&amp;label=checks&amp;style=flat" alt="checks" height="20"></a>
  <a href="https://github.com/seb5594/hass-google_translator-integration#license"><img src="https://img.shields.io/github/license/seb5594/hass-google_translator-integration?label=license&amp;style=flat" alt="license" height="20"></a>
</p>
<!-- header:end -->

🇩🇪 [Deutsche Version](README.de.md)

Use [Google Translate](https://translate.google.com) from anywhere in Home Assistant: translate texts
and structured files from automations, scripts, dashboards or other integrations, and keep an eye on
how many characters you have used this month. It works **without an account**, and with an API key
for the official Cloud Translation API if you want a service with a contract.

It is the counterpart of [DeepL Translator](https://github.com/seb5594/hass-deepl_translator-integration)
and answers in the same shape, so the
[Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration)
can use either of them, or both.

## What you get

- **`google_translator.translate_text`**: one or many texts in, translations out. The result is
  returned to the caller, so any automation, script or integration can use it.
- **`google_translator.translate_structure`**: translates only the text values of JSON or YAML data
  and files and keeps their layout. Administrators only.
- **`google_translator.get_languages`** and **`google_translator.get_usage`**: what Google offers,
  and how much of the month's character budget is used.
- Usage sensors, a translation cache, request checks that refuse a request *before* anything is
  sent, reauthentication and diagnostics without your key.

## Free, or with an API key?

| | Without an account | Cloud Translation API (API key) |
| --- | --- | --- |
| Cost | Free | The first 500,000 characters per month are free; beyond that Google charges |
| Needs | Nothing | A Google Cloud project, the API enabled and a **billing account** (a payment method) |
| Official | No: the endpoint behind translate.google.com | Yes, with terms and support |
| Reliability | Google may limit or change it at any time; heavy use gets a temporary block | Stable |
| Good for | Occasional translations, trying things out, translating a few integrations | Regular or business use |

Start without an account. If Google ever answers "limiting requests", switch to a key. The
integration helps you stay inside the free tier: the **monthly character limit** (500,000 by default
for a key) refuses any request that would go beyond it, before anything is sent. Google offers no
way to read your real usage, so the integration counts what *it* sent; translations made with the
same key elsewhere are not included. Set a billing budget alert in the Google Cloud console as well.

## Installation

Install it with HACS (add this repository as a custom repository of the type *Integration*), or copy
`custom_components/google_translator` into the `custom_components` folder of your configuration and
restart Home Assistant.

## Setup

After downloading and restarting Home Assistant, **Google Translator** appears under
*Settings > Devices & services > Discovered*. Select **Configure** and choose how to reach Google.
The suggestion uses this Home Assistant instance's own mDNS advertisement, so nothing outside your
network is asked, and it stops once an account exists. Ignored suggestions stay ignored.
Zeroconf/mDNS must be enabled; it is part of the usual `default_config`.

If no suggestion appears, open *Settings > Devices & services > Add integration* and pick
**Google Translator**.

### Without an account

Choose *Free, no account*, check the default target language (preselected from your server
language) and submit. A test translation proves that it works.

### With a Cloud Translation API key

1. In the [Google Cloud console](https://console.cloud.google.com) create a project, enable the
   **Cloud Translation API** and add a billing account.
2. Under *APIs & Services > Credentials* create an **API key**. Restrict it to the Cloud Translation
   API.
3. Choose *Cloud Translation API (API key)* in Home Assistant and paste the key.

### YAML

Instead of using the UI, one account can be set up in `configuration.yaml`. The shortest form is
an empty block, which sets up the free account without a key:

```yaml
google_translator:
```

With all options:

```yaml
google_translator:
  api_key: !secret google_translate_key   # optional; without it the free web endpoint is used
  default_target_language: de
  monthly_character_limit: 500000         # 0 = no limit
  cache_size: 256
  discover_translator: true
```

| Option | Default | Meaning |
| --- | --- | --- |
| `api_key` | none | A Cloud Translation API key. Leave it out for the free account. |
| `default_target_language` | server language | Used when a call names no target language. |
| `monthly_character_limit` | 500000 with a key, 0 without | Requests beyond it are refused. 0 turns the limit off. |
| `cache_size` | 256 | Translations kept in memory (0–5000, 0 turns the cache off). |
| `discover_translator` | `true` | Offer the optional Custom Integration Translator. |

Restart Home Assistant to import the settings into a normal config entry. An existing account is
reused; repeated starts, rotating the key or adding and dropping it update the same account instead
of adding a duplicate. Values written in YAML win over changes made in the options dialog;
options you leave out keep their value. Removing the block keeps the account, which can then be
managed or deleted in the UI. YAML manages one account.

## Using it

```yaml
action: google_translator.translate_text
data:
  text: "Good morning!"
  target_language: de
response_variable: result
# result.text == "Guten Morgen!"
```

| Field | Meaning |
| --- | --- |
| `text` | One text or a list of texts. |
| `target_language` | A Google language code such as `de` or `zh-CN`. Spellings like `DE`, `zh_hans` or `he` are matched to the list Google offers. Defaults to the language set up for the account. |
| `source_language` | Leave empty to let Google detect it. |
| `config_entry_id` | Only needed with more than one account. |

The response contains `text` (the first translation), `translations` (every one, with the detected
source language) and `target_language`.

**Safety checks.** A request is checked completely first: the languages (the keyless endpoint would
otherwise answer an unknown target with the unchanged text), the size of every text and the monthly
budget. If it cannot be translated completely, it fails with a message ending in *Nothing was sent
to Google.*

`google_translator.translate_structure` takes inline `data` or an `input_file`, translates only text
values, never keys, skips identifiers such as URLs, entity IDs and icons, and keeps indentation, key
order, quoting and comments of files. Use `only_keys` for configuration files and `dry_run: true`
to see what would be translated and how many characters it costs. Placeholders (`{name}`, `%s`,
`{{ template }}`) are replaced by tokens and checked afterwards; if Google changes one, the call fails
instead of writing a broken text.

## Sensors

Each account gets sensors for the characters used this month, the monthly limit, the characters
remaining, the share of the budget used and (disabled by default) the end of the counting period.
The count starts from zero on the first of every month (UTC) and survives restarts. The limit and
remaining figures are unknown while no limit is set.

## Custom Integration Translator

If the [Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration)
(2026.11.17.1 or newer) is installed, Google Translator offers its setup after startup or after an
installation with HACS. Once it is set up, Google shows up in its workspace automatically; with
DeepL installed as well you choose per translation, and can let it fall back to the other service.
Turn the offer off with `discover_translator: false` or in the options.

## Good to know

- Without an account the integration uses an endpoint that Google does not document for third
  parties. It sends small requests, spaced out, and tells you when Google limits it. If your use is
  more than occasional, or you need a guarantee, use an API key. You are responsible for following
  Google's terms of service.
- Texts you translate are sent to Google. Do not translate anything you must not share.
- Documents (Word, PDF and so on) are not supported; Google offers that only in the advanced API.
- Google, Google Translate and Google Cloud are trademarks of Google LLC. This project is not
  affiliated with or endorsed by Google.

<!-- support:begin (generated, shared text) -->
## Say thanks

All my projects are built in my spare time, just for the fun of it. Still, they take a lot of time and care, and many of the smart home gadgets I buy end up here because I want to make them cloud-free and smart-home ready. Every bit of support means a lot to me.

If my work helped you or turned out to be useful, show your appreciation with a hot drink for my next sleepless night.

[![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/seb5594) [![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/seb5594)
<!-- support:end -->

<!-- license:begin (generated from the license file) -->
## License

[![license](https://img.shields.io/static/v1?label=license&message=Apache-2.0&color=5B6770&style=flat)](LICENSE)

Published under the [Apache License 2.0](LICENSE).
<!-- license:end -->
