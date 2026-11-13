# GUI translations

Choose **Settings → Language** to change the interface without restarting.
The default follows the system language; English is the fallback. The choice is
saved on this computer and does not change controller firmware or profiles.

The initial catalogs cover Traditional and Simplified Chinese, Vietnamese,
Russian, Spanish, Brazilian Portuguese, German, French and Japanese. They are
initial translations and welcome review by native speakers, especially hardware
terminology. Technical diagnostic reports and raw device errors remain in English
so they can be compared in bug reports. Product names, physical button labels,
keyboard keys and protocol identifiers are preserved.

Open `deadband_<locale>.ts` in **Qt Linguist** and edit the translations there.
The source language is English. Preserve `%1`, `%2` and any file patterns such as
`*.png`; placeholders can be moved to suit the language's word order. Identical
UI wording shares the `UI` translation context across pages.

After changing English UI text, extract new strings with:

```sh
python3 tools/translations.py --update
```

After editing translations, rebuild the runtime catalogs with:

```sh
python3 tools/translations.py
python3 -m unittest discover -s tests -p test_i18n.py
```

The helper uses `pyside6-lupdate`/`pyside6-lrelease`, `lupdate6`/`lrelease6` or
the unversioned Qt tools. Install Qt Linguist tools for translation development;
normal users do not need them. Commit both `.ts` and compiled `.qm` files so
running from source, AUR installs and AppImages all have the same translations.
Unfinished entries fall back to English until completed and compiled.

To add another language, add its code and native name to `LANGUAGES` in `i18n.py`,
create `translations/deadband_<code>.ts` with `lupdate`, and translate it. For
labels supplied by a bridge, mark the English text with `QT_TRANSLATE_NOOP` in
`i18n.py` and translate it only at display time. Never pass a translated label
back as a protocol key or use it to decide which page or setting is selected.
