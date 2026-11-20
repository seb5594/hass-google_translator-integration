# Google Translator

**🇩🇪 Deutsch** · [🇬🇧 English](README.md)

Nutze [Google Übersetzer](https://translate.google.com) überall in Home Assistant: Übersetze Texte und
strukturierte Dateien aus Automatisierungen, Skripten, Dashboards oder anderen Integrationen und behalte
im Blick, wie viele Zeichen du diesen Monat verbraucht hast. Es funktioniert **ohne Konto** und mit einem
API-Schlüssel für die offizielle Cloud Translation API, wenn du einen Dienst mit Vertrag möchtest.

Die Integration ist das Gegenstück zu [DeepL Translator](https://github.com/seb5594/hass-deepl_translator-integration)
und antwortet im gleichen Format. Der
[Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration)
kann deshalb beide nutzen, einzeln oder zusammen.

## Funktionen

- **`google_translator.translate_text`**: ein oder mehrere Texte hinein, Übersetzungen heraus. Das Ergebnis
  geht an den Aufrufer zurück, jede Automatisierung, jedes Skript und jede Integration kann es verwenden.
- **`google_translator.translate_structure`**: übersetzt nur die Textwerte von JSON- oder YAML-Daten und
  -Dateien und behält deren Layout. Nur für Administratoren.
- **`google_translator.get_languages`** und **`google_translator.get_usage`**: was Google anbietet und wie viel
  des Zeichenbudgets im Monat verbraucht ist.
- Verbrauchssensoren, ein Übersetzungs-Cache, Prüfungen, die eine Anfrage ablehnen, *bevor* etwas gesendet
  wird, Neuanmeldung und Diagnose ohne deinen Schlüssel.

## Kostenlos oder mit API-Schlüssel?

| | Ohne Konto | Cloud Translation API (API-Schlüssel) |
| --- | --- | --- |
| Kosten | Kostenlos | Die ersten 500.000 Zeichen pro Monat sind frei, darüber berechnet Google |
| Voraussetzung | Keine | Ein Google-Cloud-Projekt, aktivierte API und ein **Rechnungskonto** (Zahlungsmittel) |
| Offiziell | Nein: der Zugang hinter translate.google.com | Ja, mit Bedingungen und Support |
| Verlässlichkeit | Google kann ihn jederzeit begrenzen oder ändern, bei starker Nutzung droht eine zeitweise Sperre | Stabil |
| Geeignet für | Gelegentliche Übersetzungen, Ausprobieren, einige Integrationen übersetzen | Regelmäßige oder geschäftliche Nutzung |

Beginne ohne Konto. Meldet Google irgendwann „limiting requests“, wechsle zu einem Schlüssel. Die Integration
hilft dir, im kostenlosen Kontingent zu bleiben: Das **monatliche Zeichenlimit** (mit Schlüssel standardmäßig
500.000) lehnt jede Anfrage ab, die darüber hinausginge, bevor etwas gesendet wird. Google bietet keine
Möglichkeit, den echten Verbrauch zu lesen, deshalb zählt die Integration, was *sie* gesendet hat;
Übersetzungen mit demselben Schlüssel an anderer Stelle sind nicht enthalten. Richte zusätzlich eine
Budget-Warnung in der Google Cloud Console ein.

## Installation

### HACS oder Marketplace

1. Suche in HACS (Home Assistant 2026.10 und älter) oder unter **Einstellungen → Marketplace**
   (2026.11 und neuer) nach **Google Translator**, oder nutze das Badge *HACS · Marketplace* oben.
2. Lade die Integration herunter und starte Home Assistant neu.

Findet die Suche sie nicht, füge `https://github.com/seb5594/hass-google_translator-integration` am selben Ort als
benutzerdefiniertes Repository hinzu (Kategorie *Integration*) und lade sie von dort herunter.

### Manuell

Kopiere `custom_components/google_translator` in den Ordner `custom_components` deiner Konfiguration und
starte Home Assistant neu.

## Einrichtung

Nach dem Herunterladen und einem Neustart erscheint **Google Translator** unter
*Einstellungen > Geräte & Dienste > Entdeckt*. Wähle **Konfigurieren** und lege fest, wie Google erreicht
wird. Der Vorschlag nutzt die eigene mDNS-Ankündigung dieser Home-Assistant-Instanz, es wird also nichts
außerhalb deines Netzwerks gefragt, und er endet, sobald ein Konto existiert. Ignorierte Vorschläge bleiben
ignoriert. Zeroconf/mDNS muss aktiviert sein; es gehört zur üblichen `default_config`.

Erscheint kein Vorschlag, öffne *Einstellungen > Geräte & Dienste > Integration hinzufügen* und wähle
**Google Translator**.

### Ohne Konto

Wähle *Kostenlos, ohne Konto*, prüfe die Standard-Zielsprache (aus deiner Serversprache vorbelegt) und sende
ab. Eine Testübersetzung zeigt, dass es funktioniert.

### Mit Cloud-Translation-API-Schlüssel

1. Erstelle in der [Google Cloud Console](https://console.cloud.google.com) ein Projekt, aktiviere die
   **Cloud Translation API** und füge ein Rechnungskonto hinzu.
2. Erstelle unter *APIs & Dienste > Anmeldedaten* einen **API-Schlüssel** und beschränke ihn auf die Cloud
   Translation API.
3. Wähle in Home Assistant *Cloud Translation API (API-Schlüssel)* und füge den Schlüssel ein.

### YAML

Statt der Oberfläche lässt sich ein Konto in der `configuration.yaml` einrichten. Am kürzesten ist ein leerer
Block, der das kostenlose Konto ohne Schlüssel einrichtet:

```yaml
google_translator:
```

Mit allen Optionen:

```yaml
google_translator:
  api_key: !secret google_translate_key   # optional; ohne ihn wird der kostenlose Web-Zugang genutzt
  default_target_language: de
  monthly_character_limit: 500000         # 0 = kein Limit
  cache_size: 256
  discover_translator: true
```

| Option | Standard | Bedeutung |
| --- | --- | --- |
| `api_key` | keiner | Ein Cloud-Translation-API-Schlüssel. Weglassen für das kostenlose Konto. |
| `default_target_language` | Serversprache | Wird genutzt, wenn ein Aufruf keine Zielsprache nennt. |
| `monthly_character_limit` | 500000 mit Schlüssel, 0 ohne | Anfragen darüber hinaus werden abgelehnt. 0 schaltet das Limit aus. |
| `cache_size` | 256 | Im Speicher gehaltene Übersetzungen (0–5000, 0 schaltet den Cache aus). |
| `discover_translator` | `true` | Den optionalen Custom Integration Translator anbieten. |

Starte Home Assistant neu, um die Einstellungen in einen normalen Konfigureintrag zu importieren. Ein
vorhandenes Konto wird wiederverwendet; wiederholte Starts, ein neuer Schlüssel sowie das Hinzufügen und
Entfernen des Schlüssels aktualisieren dasselbe Konto, statt ein zweites anzulegen. Werte aus YAML haben
Vorrang vor Änderungen im Optionsdialog; weggelassene Optionen behalten ihren Wert. Wird der Block entfernt,
bleibt das Konto bestehen und lässt sich in der Oberfläche verwalten oder löschen. YAML verwaltet ein Konto.

## Verwendung

```yaml
action: google_translator.translate_text
data:
  text: "Good morning!"
  target_language: de
response_variable: result
# result.text == "Guten Morgen!"
```

| Feld | Bedeutung |
| --- | --- |
| `text` | Ein Text oder eine Liste von Texten. |
| `target_language` | Ein Google-Sprachcode wie `de` oder `zh-CN`. Schreibweisen wie `DE`, `zh_hans` oder `he` werden der Liste von Google zugeordnet. Standard ist die Sprache des Kontos. |
| `source_language` | Leer lassen, damit Google sie erkennt. |
| `config_entry_id` | Nur bei mehr als einem Konto nötig. |

Die Antwort enthält `text` (die erste Übersetzung), `translations` (alle, mit erkannter Quellsprache) und
`target_language`.

**Sicherheitsprüfungen.** Eine Anfrage wird zuerst vollständig geprüft: die Sprachen (der schlüssellose
Zugang würde eine unbekannte Zielsprache sonst mit dem unveränderten Text beantworten), die Größe jedes Textes
und das Monatsbudget. Lässt sie sich nicht vollständig übersetzen, scheitert sie mit einer Meldung, die mit
*Nothing was sent to Google.* endet.

`google_translator.translate_structure` nimmt `data` direkt oder eine `input_file`, übersetzt nur Textwerte,
nie Schlüssel, überspringt Kennungen wie URLs, Entitäts-IDs und Symbole und behält Einrückung,
Schlüsselreihenfolge, Anführungszeichen und Kommentare von Dateien. Nutze `only_keys` für Konfigurationsdateien
und `dry_run: true`, um zu sehen, was übersetzt würde und wie viele Zeichen es kostet. Platzhalter (`{name}`,
`%s`, `{{ template }}`) werden durch Marker ersetzt und danach geprüft; verändert Google einen, schlägt der
Aufruf fehl, statt einen kaputten Text zu schreiben.

## Sensoren

Jedes Konto erhält Sensoren für die Zeichen dieses Monats, das Monatslimit, die verbleibenden Zeichen, den
verbrauchten Anteil des Budgets und (standardmäßig deaktiviert) das Ende des Zählzeitraums. Die Zählung
beginnt am Ersten jedes Monats (UTC) bei null und übersteht Neustarts. Limit und Rest sind unbekannt, solange
kein Limit gesetzt ist.

## Custom Integration Translator

Ist der [Custom Integration Translator](https://github.com/seb5594/hass-custom_integrations_translator-integration)
(2026.11.17.1 oder neuer) installiert, bietet Google Translator nach dem Start oder nach einer Installation
über HACS seine Einrichtung an. Danach erscheint Google automatisch in dessen Arbeitsbereich; ist auch DeepL
installiert, wählst du pro Übersetzung und kannst auf den jeweils anderen Dienst ausweichen lassen. Das
Angebot schaltest du mit `discover_translator: false` oder in den Optionen ab.

## Gut zu wissen

- Ohne Konto nutzt die Integration einen Zugang, den Google für Dritte nicht dokumentiert. Sie sendet kleine,
  zeitlich gestreckte Anfragen und meldet, wenn Google sie begrenzt. Ist deine Nutzung mehr als gelegentlich
  oder brauchst du eine Zusage, nutze einen API-Schlüssel. Du bist selbst dafür verantwortlich, die
  Nutzungsbedingungen von Google einzuhalten.
- Texte, die du übersetzt, werden an Google gesendet. Übersetze nichts, das du nicht weitergeben darfst.
- Dokumente (Word, PDF usw.) werden nicht unterstützt; Google bietet das nur in der erweiterten API an.
- Google, Google Übersetzer und Google Cloud sind Marken von Google LLC. Dieses Projekt steht in keiner
  Verbindung zu Google und wird nicht von Google unterstützt.

<!-- support:begin (generated, shared text) -->
## Say thanks

All my projects are built in my spare time, just for the fun of it. Still, they take a lot of time and care, and many of the smart home gadgets I buy end up here because I want to make them cloud-free and smart-home ready. Every bit of support means a lot to me.

If my work helped you or turned out to be useful, show your appreciation with a hot drink for my next sleepless night.

[![PayPal](https://img.shields.io/static/v1?label=Support&message=PayPal&color=0070BA&logo=paypal&logoColor=white&style=for-the-badge)](https://paypal.me/seb5594) [![Buy Me a Coffee](https://img.shields.io/static/v1?label=Support&message=Buy%20Me%20a%20Coffee&color=FFDD00&logo=buy-me-a-coffee&logoColor=black&style=for-the-badge)](https://buymeacoffee.com/seb5594)
<!-- support:end -->

<!-- license:begin (generated from the license file) -->
## License

[![license](https://img.shields.io/static/v1?label=license&message=MIT&color=5B6770&style=flat)](LICENSE)

Published under the [MIT License](LICENSE).
<!-- license:end -->


Versions use `YYYY.MM.DD` for the first build of a day, followed by `YYYY.MM.DD.1`, `.2`, and so on. Release tags have no prefix.
