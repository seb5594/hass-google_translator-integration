"""Checks that need no Home Assistant installation."""
import importlib.util
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = next((ROOT / "custom_components").iterdir())


def load_module(name):
    """Import a module of the component without importing (and needing) Home Assistant."""
    module_name = f"_isolated_{name}"
    spec = importlib.util.spec_from_file_location(module_name, COMPONENT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


def flatten(tree, prefix=""):
    """All key paths of a nested dict, ignoring the texts."""
    for key, value in tree.items():
        path = f"{prefix}{key}"
        yield path
        if isinstance(value, dict):
            yield from flatten(value, f"{path}.")


class IntegrationLayout(unittest.TestCase):
    def test_manifest_domain_matches_folder_and_constants(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(manifest["domain"], COMPONENT.name)
        self.assertIn(f'DOMAIN = "{COMPONENT.name}"', (COMPONENT / "const.py").read_text())

    def test_version_follows_the_calendar_scheme(self):
        version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
        year, month, day, build = (int(part) for part in version.split("."))
        datetime(year, month, day)  # raises for an impossible date
        self.assertGreaterEqual(build, 1)

    def test_hacs_zip_is_named_after_the_domain(self):
        hacs = json.loads((ROOT / "hacs.json").read_text())
        self.assertEqual(hacs["filename"], f"{COMPONENT.name}.zip")

    def test_translations_mirror_strings(self):
        strings = json.loads((COMPONENT / "strings.json").read_text())
        english = json.loads((COMPONENT / "translations/en.json").read_text())
        self.assertEqual(strings, english)

    def test_german_translation_covers_every_english_key(self):
        english = json.loads((COMPONENT / "translations/en.json").read_text())
        german = json.loads((COMPONENT / "translations/de.json").read_text())
        self.assertEqual(sorted(flatten(english)), sorted(flatten(german)))

    def test_every_service_field_is_described(self):
        services = json.loads((COMPONENT / "translations/en.json").read_text())["services"]
        for name, service in services.items():
            self.assertTrue(service["name"] and service["description"], name)
            for field, texts in service["fields"].items():
                self.assertTrue(texts["name"] and texts["description"], f"{name}.{field}")

    def test_services_yaml_and_translations_list_the_same_fields(self):
        import yaml

        described = json.loads((COMPONENT / "translations/en.json").read_text())["services"]
        declared = yaml.safe_load((COMPONENT / "services.yaml").read_text())
        self.assertEqual(set(described), set(declared))
        for name, service in declared.items():
            self.assertEqual(set(service["fields"]), set(described[name]["fields"]), name)

    def test_zeroconf_matcher_targets_the_instance_advertisement(self):
        manifest = json.loads((COMPONENT / "manifest.json").read_text())
        self.assertEqual(
            manifest["zeroconf"],
            [{"type": "_home-assistant._tcp.local.", "properties": {"uuid": "*"}}],
        )


class Languages(unittest.TestCase):
    SUPPORTED = ["de", "en", "zh-CN", "zh-TW", "pt", "pt-PT", "iw", "no"]

    def setUp(self):
        self.languages = load_module("languages")

    def test_codes_are_matched_against_what_google_lists(self):
        normalize = self.languages.normalize_language
        for typed, expected in {
            "DE": "de", "zh_hans": "zh-CN", "zh-Hant": "zh-TW", "pt-BR": "pt", "pt_pt": "pt-PT",
            "he": "iw", "nb": "no", "EN-US": "en",
        }.items():
            self.assertEqual(normalize(typed, self.SUPPORTED), expected, typed)

    def test_unknown_codes_are_kept_for_the_preflight_to_refuse(self):
        self.assertEqual(self.languages.normalize_language("xx", self.SUPPORTED), "xx")

    def test_sources_lose_their_region_except_for_chinese(self):
        source = self.languages.source_language
        self.assertEqual(source("EN-US", self.SUPPORTED), "en")
        self.assertEqual(source("zh-Hant", self.SUPPORTED), "zh-TW")

    def test_home_assistant_languages_map_to_google_codes(self):
        target = self.languages.target_from_home_assistant_language
        for ha, expected in {
            "de": "de", "pt-BR": "pt", "pt": "pt", "zh-Hans": "zh-CN", "nb": "no",
            "he": "iw", "en-GB": "en", "sr-Latn": "sr", "xx": "en", None: "en",
        }.items():
            self.assertEqual(target(ha), expected, ha)


class Placeholders(unittest.TestCase):
    def setUp(self):
        self.placeholders = load_module("placeholders")

    def test_placeholders_survive_a_round_trip(self):
        shield = self.placeholders.Shield()
        text = "Hello {name}, you have %s messages and {{ states('x') }}"
        protected, originals = shield.protect(text)
        self.assertNotIn("{", protected)
        self.assertEqual(shield.restore(protected.replace("Hello", "Hallo"), originals),
                         text.replace("Hello", "Hallo"))

    def test_a_lost_or_duplicated_token_is_an_error(self):
        shield = self.placeholders.Shield()
        protected, originals = shield.protect("Open {name}")
        for broken in ("Open", protected + " " + protected):
            with self.assertRaises(self.placeholders.PlaceholderError):
                shield.restore(broken, originals)

    def test_plain_text_needs_no_protection(self):
        self.assertFalse(self.placeholders.contains_placeholder("Good morning"))
        self.assertTrue(self.placeholders.contains_placeholder("Good {time}"))


class Preflight(unittest.TestCase):
    def setUp(self):
        self.preflight = load_module("preflight")

    def test_budget_that_cannot_cover_the_request_is_refused(self):
        with self.assertRaisesRegex(self.preflight.PreflightError, "Nothing was sent"):
            self.preflight.check_budget(600, 500, "2026-12-01T00:00:00+00:00")
        self.preflight.check_budget(500, 500)
        self.preflight.check_budget(10**9, None)

    def test_unknown_language_comes_with_suggestions(self):
        with self.assertRaisesRegex(self.preflight.PreflightError, "Did you mean de"):
            self.preflight.check_language("dd", ["de", "en"], "target")
        self.preflight.check_language("de", ["de", "en"], "target")
        self.preflight.check_language("anything", None, "target")

    def test_oversized_text_is_refused(self):
        with self.assertRaises(self.preflight.PreflightError):
            self.preflight.check_text_sizes(["x" * 11], 10)
        self.preflight.check_text_sizes(["x" * 10], 10)


class Usage(unittest.TestCase):
    class Memory:
        def __init__(self, stored=None):
            self.stored, self.saved = stored, None

        async def async_load(self):
            return self.stored

        async def async_save(self, data):
            self.saved = data

        def async_delay_save(self, data_func, delay=0):
            self.saved = data_func()

    def setUp(self):
        self.usage = load_module("usage")
        self.now = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

    def tracker(self, storage=None, limit=1000):
        return self.usage.UsageTracker(storage or self.Memory(), limit, lambda: self.now)

    def test_characters_are_counted_and_reported_against_the_budget(self):
        tracker = self.tracker()
        tracker.add(250)
        figures = tracker.usage
        self.assertEqual((figures.character_count, figures.characters_remaining), (250, 750))
        self.assertEqual(figures.usage_percent, 25.0)
        self.assertEqual(figures.period_end, "2026-12-01T00:00:00+00:00")

    def test_without_a_limit_nothing_is_remaining_or_a_percentage(self):
        figures = self.tracker(limit=0).usage
        self.assertTrue(figures.is_unlimited)
        self.assertIsNone(figures.characters_remaining)
        self.assertIsNone(figures.usage_percent)

    def test_the_count_survives_a_restart_within_the_month_only(self):
        import asyncio

        storage = self.Memory()
        tracker = self.tracker(storage)
        tracker.add(40)
        self.assertEqual(storage.saved, {"period": "2026-11", "characters": 40})
        restored = self.tracker(self.Memory(storage.saved))
        asyncio.run(restored.async_load())
        self.assertEqual(restored.usage.character_count, 40)
        self.now = datetime(2026, 12, 1, tzinfo=timezone.utc)
        self.assertEqual(restored.usage.character_count, 0)

    def test_listeners_hear_about_every_change_until_they_stop(self):
        tracker = self.tracker()
        heard = []
        stop = tracker.async_add_listener(lambda: heard.append(1))
        tracker.add(1)
        stop()
        tracker.add(1)
        self.assertEqual(len(heard), 1)

    def test_months_roll_over_in_december(self):
        start, end = self.usage.month_bounds(datetime(2026, 12, 31, 23, tzinfo=timezone.utc))
        self.assertEqual((start.month, end.year, end.month), (12, 2027, 1))


if __name__ == "__main__":
    unittest.main()
