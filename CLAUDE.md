# Instrukce pro AI agenty

Kontext a plné technické rozhodnutí viz [docs/spec.md](docs/spec.md). Tento soubor obsahuje jen
pravidla chování při práci na repu.

## Nejdůležitější fakta o projektu

`.winstrom-backup` je **PostgreSQL custom-format dump** (`pg_dump -Fc`), ne ZIP/XML. Čte se přes
`pgdumplib`, čistě v Pythonu, bez nutnosti mít nainstalovaný PostgreSQL. Pokud narazíš na
dokumentaci nebo předpoklad, že jde o XML — je zastaralý, řiď se `docs/spec.md`.

Toto je **primárně osobní nástroj autora**, ne udržovaný open-source projekt. Kód je veřejný jako
inspirace pro ostatní, ale nestavíme robustnost proti neznámému schématu cizích FlexiBee instalací —
optimalizujeme pro strukturu ověřenou na reálné záloze autora (viz `docs/spec.md`). Nepřidávej
scaffolding pro cizí přispěvatele (issue templates, contribution guide, podpora více verzí schématu),
pokud o to autor výslovně nepožádá. Bezpečnostní rigor okolo účetních dat (dry-run, idempotence,
e2e testy, rollback) naopak neslevuj — je to o to důležitější, že tu není komunita, která by chybu
zachytila dřív než sám autor na svém ostrém účtu.

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
- **Unit testy běží bez zálohy a bez sítě.** Parser/mapper testy používají fixtures v
  `tests/fixtures/` (vzorové řádky/tuples), ne reálný `.winstrom-backup`.
- **End-to-end testy nikdy neběží proti reálnému Fakturoid účtu ani sandboxu.** Celý `migrate` flow
  (CLI → httpx → HTTP → dedup/idempotence → report) se testuje proti lokálnímu mock serveru v
  `tests/mock_fakturoid/` (viz [docs/spec.md#testing-strategy](docs/spec.md#testing-strategy)).
  Tohle je nedílná součást implementace, ne volitelný nice-to-have — projekt zapisuje do účetnictví
  uživatele, takže "otestováno jen na papíře / jen unit testy mapperu" nestačí k tomu, aby se import
  považoval za hotový. Reálný Fakturoid sandbox account zůstává jen pro ruční, jednorázovou
  verifikaci před releasem, ne pro automatizované testy v CI.
- **Token se nikdy neukládá na disk.** Ani do logů, ani do cache souborů. Jen env proměnná
  `FAKTUROID_TOKEN` nebo interaktivní prompt s `hide_input=True`.
- **Každý reálný (`--yes`) běh persistuje run log.** Idempotence (dedup) chrání proti duplicitám,
  ne proti špatně namapovaným datům — pokud se najde bug až po produkčním běhu, run log je jediný
  způsob, jak bezpečně smazat přesně to, co migrace vytvořila, přes `f2f rollback <run-id>`, aniž by
  se sáhlo na cokoliv, co uživatel ve Fakturoidu vytvořil sám. Viz
  [docs/spec.md#rollback--failure-recovery](docs/spec.md#rollback--failure-recovery). Produkční běh
  je jednorázová událost, ne iterační smyčka — veškeré ladění mapperu patří na sandbox.
- **Neber si závislosti navíc bez důvodu.** Tech stack je záměrně minimální (httpx, pydantic,
  typer, rich, pgdumplib) — držet se ho, nepřidávat XML parsery, ORM, browser automation apod.
- **Poetry, ne pip/uv přímo.** Závislosti přidávej přes `poetry add`, ne ruční editací
  `pyproject.toml` bez `poetry lock`.

## Otevřené otázky

Viz sekce **Open Questions** v [docs/spec.md](docs/spec.md#open-questions) a odpovídající GitHub
issues. Pokud narazíš na rozhodnutí, které tam není zodpovězené (např. jak naložit se
zálohovými fakturami, stornovanými doklady, nebo institucionálními kontakty jako zdravotní
pojišťovna) — zeptej se uživatele, nepředpokládej chování.
