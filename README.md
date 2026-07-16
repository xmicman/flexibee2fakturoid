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
4. `poetry run f2f migrate firma.winstrom-backup --fakturoid-slug <slug> --fakturoid-token <token>` —
   dry-run (výchozí), přidej `--yes` pro reálný import

## Stav projektu

Rané vývojové fáze — viz [otevřené issues](../../issues) pro aktuální plán a
[docs/spec.md](docs/spec.md) pro plnou technickou specifikaci.

## Vývoj

Viz [CLAUDE.md](CLAUDE.md) pro konvence a instrukce pro AI agenty pracující na tomto repu.

```bash
poetry install
poetry run pytest
poetry run ruff check .
```

## Licence

MIT
