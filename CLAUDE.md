# Instrukce pro AI agenty

Kontext a plné technické rozhodnutí viz [docs/spec.md](docs/spec.md). Tento soubor obsahuje jen
pravidla chování při práci na repu.

## Nejdůležitější fakt o projektu

`.winstrom-backup` je **PostgreSQL custom-format dump** (`pg_dump -Fc`), ne ZIP/XML. Čte se přes
`pgdumplib`, čistě v Pythonu, bez nutnosti mít nainstalovaný PostgreSQL. Pokud narazíš na
dokumentaci nebo předpoklad, že jde o XML — je zastaralý, řiď se `docs/spec.md`.

## Pravidla

- **Backup soubor nikdy necommituj.** Je v `.gitignore` (`*.winstrom-backup`) — obsahuje reálná
  účetní data uživatele. Totéž pro `.env` a `*.json` v rootu (tokeny, credentials).
- **`f2f inspect <backup>` napřed, kód pak.** Než napíšeš parser nebo mapper pro novou entitu,
  ověř přes `inspect` skutečný obsah a názvy sloupců té tabulky v reálné záloze. Struktura FlexiBee
  DB se může lišit mezi verzemi/instalacemi — nepředpokládej, ověř.
- **Dry-run je výchozí chování.** Migrace bez `--yes` nesmí nikdy zapisovat do Fakturoidu. Nepřidávej
  žádnou cestu, kde by se import spustil bez explicitního potvrzení.
- **Idempotence.** Import musí být bezpečné spustit opakovaně — dedup přes IČO (kontakty) a číslo
  faktury (faktury). Nikdy nevytvářej duplicitní záznam ve Fakturoidu.
- **Testy běží bez zálohy a bez sítě.** Unit testy parseru/mapperu používají fixtures v
  `tests/fixtures/` (vzorové řádky/tuples), ne reálný `.winstrom-backup` a ne živé volání
  Fakturoid API. Síťové/integrační testy (pokud vzniknou) jasně odděl a označ.
- **Token se nikdy neukládá na disk.** Ani do logů, ani do cache souborů. Jen env proměnná
  `FAKTUROID_TOKEN` nebo interaktivní prompt s `hide_input=True`.
- **Neber si závislosti navíc bez důvodu.** Tech stack je záměrně minimální (httpx, pydantic,
  typer, rich, pgdumplib) — držet se ho, nepřidávat XML parsery, ORM, browser automation apod.
- **Poetry, ne pip/uv přímo.** Závislosti přidávej přes `poetry add`, ne ruční editací
  `pyproject.toml` bez `poetry lock`.

## Otevřené otázky

Viz sekce **Open Questions** v [docs/spec.md](docs/spec.md#open-questions) a odpovídající GitHub
issues. Pokud narazíš na rozhodnutí, které tam není zodpovězené (např. jak naložit se
zálohovými fakturami, stornovanými doklady, nebo institucionálními kontakty jako zdravotní
pojišťovna) — zeptej se uživatele, nepředpokládej chování.
