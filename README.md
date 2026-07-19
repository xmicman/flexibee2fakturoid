# flexibee2fakturoid

Jednorázový migrační CLI nástroj pro přesun dat z [FlexiBee](https://www.flexibee.eu/) do
[Fakturoidu](https://www.fakturoid.cz/): dodavatelé, odběratelé, přijaté a vydané faktury (s
zachováním číslování).

Žádné API připojení k FlexiBee, žádná browser automation. Stačí jednorázová záloha firmy
stažená z FlexiBee UI.

## Jak na to

1. FlexiBee → **Nástroje → Záloha firmy** → uložit jako `firma.winstrom-backup`
2. `poetry install`
3. `poetry run f2f inspect firma.winstrom-backup` — ukáže, co záloha obsahuje
4. `poetry run f2f migrate firma.winstrom-backup --fakturoid-slug <slug> --fakturoid-token <token> --only contacts` —
   dry-run (výchozí), přidej `--yes` pro reálný import
5. Doporučeno: první ostrý běh omezit na aktuální rok —
   `--only issued-invoices --since 2026-01-01`, pak `--only received-invoices --since 2026-01-01`.
   Historie se doimportuje postupně později (viz
   [docs/spec.md#cutover-strategie-postupný-import](docs/spec.md#cutover-strategie-postupný-import)).
6. Pokud se něco pokazí po `--yes` běhu: `f2f rollback <run-id>` vrátí zpět přesně to, co ten běh
   vytvořil (run-id se vypíše na konci každého `--yes` běhu).

## Stav projektu

Fáze 1–4 (backup parser, kontakty, vydané i přijaté faktury) a rollback jsou implementované a
end-to-end otestované proti mock Fakturoid serveru i proti reálné záloze (dry-run/mock-server run,
nikdy proti produkčnímu Fakturoid účtu). **Před prvním skutečným `--yes` během na ostrém účtu** je
potřeba ručně ověřit pár věcí proti reálnému Fakturoid API/sandboxu — zejména podporu vlastního
čísla faktury (Q3) a přesný endpoint pro přijaté faktury (Q2), viz
[docs/spec.md — Open Questions](docs/spec.md#open-questions). Detailní stav viz
[issues](../../issues) a [docs/spec.md](docs/spec.md).

## Vývoj

Viz [CLAUDE.md](CLAUDE.md) pro konvence a instrukce pro AI agenty pracující na tomto repu.

```bash
poetry install
poetry run pytest
poetry run ruff check .
```

## Licence

MIT
