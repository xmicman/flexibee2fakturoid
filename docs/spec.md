# flexibee2fakturoid — Technická specifikace

> Stav: Draft v0.3 — backup-first přístup, ověřeno proti reálné záloze.
> Nahrazuje artefakt v0.2, který předpokládal jiný formát zálohy (viz [Historie](#historie-verzí) níže).

## Goal

Jednorázový migrační nástroj (CLI) pro přesun dat z FlexiBee do Fakturoidu. Bez API přístupu k FlexiBee,
bez browser automation — uživatel vytvoří zálohu v FlexiBee UI jedním kliknutím a předá soubor nástroji.

Data k migraci: **dodavatelé, odběratelé, přijaté faktury, vydané faktury.** Číslování faktur zachováno.

## Approach

FlexiBee umožňuje zálohu celé firmy přes **Nástroje → Záloha firmy** (dostupné všem uživatelům, bez
placení API). Vývoj iteruje nad tím samým souborem — server FlexiBee se vůbec nekontaktuje.

### Tok dat

```
FlexiBee UI (Záloha firmy) → .winstrom-backup → Python parser (pgdumplib) → Mapper → Fakturoid API (REST v3)
```

### Jak uživatel vytvoří zálohu

1. Přihlásit se do FlexiBee
2. Horní menu → **Nástroje → Záloha firmy**
3. Uložit soubor jako `firma.winstrom-backup`
4. Spustit: `f2f migrate firma.winstrom-backup …`

## Backup formát (.winstrom-backup) — SKUTEČNÝ FORMÁT

> **Zásadní zjištění oproti v0.2:** Soubor `.winstrom-backup` **není ZIP archiv s XML**. Je to
> **PostgreSQL custom-format dump** (výstup `pg_dump -Fc`), tedy binární export celé databáze firmy
> ve FlexiBee — schéma (tabulky, funkce, triggery) i data. Ověřeno na reálné záloze:
> `file` hlásí `PostgreSQL custom database dump - v1.14-0`, `pg_restore --list` vrací 4935 TOC záznamů,
> z toho 282 tabulek s daty.

FlexiBee (postavené na enginu ABRA/Winstrom) interně používá Postgres. Záloha firmy je proto přímý dump
té databáze — sloupce v tabulkách odpovídají stejným polím, která zná i Winstrom XML/REST API, jen bez
XML obálky a s číselnými FK vazbami místo `code:XXX` referencí.

<a id="parsing"></a>
### Jak zálohu číst

Bez nutnosti mít nainstalovaný a běžící PostgreSQL server nebo systémový `pg_restore` (ověřeno):

```python
import pgdumplib

d = pgdumplib.load("firma.winstrom-backup")

# Iterace přes řádky tabulky — vrací tuple hodnot v pořadí sloupců z COPY statementu
for row in d.table_data("public", "aadresar"):
    ...
```

Pořadí sloupců pro danou tabulku lze získat z `copy_stmt` příslušného TOC entry:

```python
import re

def columns_for(dump: pgdumplib.Dump, table: str) -> list[str]:
    entry = dump.lookup_entry("TABLE DATA", "public", table)
    match = re.search(r"\((.*?)\)\s*FROM", entry.copy_stmt, re.S)
    return [c.strip() for c in match.group(1).split(",")]
```

Ruční inspekce zálohy bez Pythonu (vyžaduje nainstalovaný PostgreSQL klient, jen pro debugging):

```bash
pg_restore --list firma.winstrom-backup | less        # obsah zálohy (TOC)
pg_restore --schema-only -t ddoklfak -f - firma.winstrom-backup   # schéma jedné tabulky
pg_restore --data-only -t aadresar -f - firma.winstrom-backup     # data jedné tabulky (plain SQL)
```

<div style="border-left:3px solid orange;padding-left:1em">
<strong>Ověřit při Fázi 1</strong><br>
Struktura a názvy sloupců se mohou lišit podle verze FlexiBee. <code>f2f inspect</code> musí být první
nástroj napsaný — ověřuje realitu dřív, než se staví parser na předpokladech.
</div>

### Klíčové tabulky

| Tabulka | Obsah | Poznámka |
|---|---|---|
| `aadresar` | Kontakty (dodavatelé i odběratelé v jedné tabulce) | 615 řádků v testovací záloze |
| `ddoklfak` | Hlavičky **všech** typů dokladů (faktury, banka, pokladna, sklad, objednávky…) | Filtrovat sloupcem `modul` |
| `dpolfak` | Položky faktur | FK `iddoklfak` → `ddoklfak.iddoklfak` |
| `dtypdokl` | Číselník typů dokladů (FAKTURA, ZÁLOHA, ZDD, dobropis…) | FK `ddoklfak.idtypdokl` |
| `astaty` | Číselník států | FK `aadresar.idfastatu`, `kod` = zkratka (ne vždy čisté ISO 3166-1 alpha-2, ověřit) |

`ddoklfak` je sdílená tabulka pro **všechny** typy dokladů v systému — faktury i bankovní pohyby,
skladové pohyby, objednávky, nabídky atd. Relevantní hodnoty sloupce `modul`:

| `modul` | Význam | Relevantní pro migraci |
|---|---|---|
| `FAV` | Faktura vydaná (issued invoice) | ✅ ano |
| `FAP` | Faktura přijatá (received invoice) | ✅ ano |
| `BAN` / `POK` | Bankovní / pokladní pohyb | ne |
| `SKL` | Skladový pohyb | ne |
| `INT` | Interní doklad | ne |
| `OBV` / `OBP` | Objednávka vydaná / přijatá | ne |
| `NAV` / `NAP` | Nabídka vydaná / přijatá | ne |
| `PPV` / `PPP` | Poptávka vydaná / přijatá | ne |
| `ZAV` / `PHL` | Ostatní závazky / pohledávky | ne (zvážit v Open Questions) |

Ověřeno na reálné záloze: 323 řádků `modul='FAV'`, 726 řádků `modul='FAP'`.

## Tech Stack

| Balíček | Verze | Účel |
|---|---|---|
| `httpx` | ≥ 0.27 | Fakturoid REST API klient |
| `pydantic` | v2 | Datové modely, validace |
| `typer` | ≥ 0.12 | CLI rozhraní |
| `rich` | ≥ 13 | Progress, tabulky, chyby v terminálu |
| `pgdumplib` | ≥ 4.0 | Čtení PostgreSQL custom-format dumpu — čistý Python, žádná systémová závislost na `pg_restore`/`libpq` |

Python **3.11+**. Správa závislostí a virtuální prostředí přes **Poetry** (`pyproject.toml` + `poetry.lock`).

> **Změna oproti v0.2:** `lxml` odstraněno (žádné XML), `uv` nahrazeno Poetry. `pgdumplib` ověřeno —
> úspěšně načte TOC (4935 entries) i data (`aadresar`: 615 řádků, `ddoklfak`: 1049 řádků) z reálné zálohy
> bez nutnosti mít nainstalovaný PostgreSQL.

## Project Structure

```
flexibee2fakturoid/
├── README.md
├── CLAUDE.md                 # instrukce pro AI agenty pracující na repu
├── pyproject.toml            # Poetry
├── docs/
│   └── spec.md               # tento dokument
├── src/f2f/
│   ├── cli.py                 # typer entry point
│   ├── flexibee/
│   │   ├── backup.py          # pgdumplib wrapper, čtení tabulek
│   │   └── models.py          # Pydantic: FlexContact, FlexInvoice…
│   ├── fakturoid/
│   │   ├── client.py          # httpx wrapper, rate limiting, retry
│   │   └── models.py          # Pydantic: Subject, Invoice…
│   └── migration/
│       ├── mapper.py          # FlexiBee → Fakturoid překlad polí
│       └── runner.py          # orchestrace, dry-run, report
└── tests/
    ├── fixtures/               # vzorové řádky/tabulky pro unit testy (bez reálné zálohy)
    └── test_mapper.py
```

Backup soubor je v `.gitignore` — spravuje ho uživatel sám, nikdy se necommituje.

## Field Mapping

### Kontakty (`aadresar` → Fakturoid `subjects`)

| FlexiBee sloupec | Fakturoid JSON | Poznámka |
|---|---|---|
| `nazev` | `name` | |
| `ic` | `registration_no` | IČO — klíč pro deduplikaci |
| `dic` | `vat_no` | DIČ |
| `email` | `email` | Obsahuje i prefix jako `" EMAILinfo@vzp.cz"` u starších záznamů — ověřit/očistit |
| `tel` | `phone` | |
| `ulice` | `street` | |
| `mesto` | `city` | |
| `psc` | `zip` | |
| `idfastatu` (FK → `astaty.kod`) | `country` | Ověřit soulad s ISO 3166-1 alpha-2 |
| `typvztahuk` | `type` | Hodnoty pozorované v datech: `typVztahu.odberatel` (customer), `typVztahu.dodavatel` (supplier), `typVztahu.odberDodav` (oboje), plus institucionální typy (`typVztahu.zdravotka`, `typVztahu.socialka`, `typVztahu.financniUrad`) — ty pravděpodobně vynechat z migrace (viz Open Questions) |

### Faktury (`ddoklfak` → Fakturoid `invoices` / `inbox_invoices`)

| FlexiBee sloupec | Fakturoid JSON | Poznámka |
|---|---|---|
| `kod` | `number` | Zachovat původní číslo (např. `VF1-0009/2024`) |
| `datvyst` | `issued_on` | |
| `datsplat` | `due_on` | |
| `duzppuv` | `taxable_fulfillment_due` | DUZP |
| `idfirmy` (FK → `aadresar.idfirmy`) | `subject_id` | Lookup: FlexiBee interní ID → Fakturoid ID vytvořené při importu kontaktů |
| `varsym` | `variable_symbol` | |
| `sumcelkem` | validace součtu | Křížová kontrola po importu |
| `modul` | rozhodnutí FAV/FAP | Filtr, ne přímé pole |
| `idtypdokl` (FK → `dtypdokl`) | — | Rozlišuje fakturu / zálohu / ZDD / dobropis — ověřit, zda se má zálohová faktura migrovat jinak |
| `storno` | — | Stornované doklady pravděpodobně přeskočit |

### Položky faktury (`dpolfak`)

| FlexiBee sloupec | Fakturoid JSON |
|---|---|
| `nazev` | `name` |
| `mnozmj` | `quantity` |
| `cenamj` | `unit_price` |
| `szbdph` | `vat_rate` |

<div style="border-left:3px solid steelblue;padding-left:1em">
<strong>Lookup tabulka kontaktů</strong><br>
Faktura odkazuje na kontakt přes číselné <code>idfirmy</code> (FK, ne string kód jako v původní v0.2
specifikaci). Runner nejdřív importuje kontakty a udržuje slovník
<code>flexibee_idfirmy → fakturoid_subject_id</code> pro překlad referencí.
</div>

## Fakturoid Import

Fakturoid REST API v3. Autentizace: **Personal Access Token (PAT)** — uživatel ho najde v nastavení účtu.

### Pořadí importu

1. Kontakty → `POST /accounts/{slug}/subjects.json`
2. Vydané faktury → `POST /accounts/{slug}/invoices.json`
3. Přijaté faktury → `POST /accounts/{slug}/inbox_invoices.json` (ověřit — viz Open Questions)

### Idempotence

Před každým importem kontrola existence záznamu — lookup přes IČO (kontakty) nebo číslo faktury (faktury).
Duplicity se přeskočí s logem. Bezpečné pro opakované spuštění.

### Rate limiting

```python
async def _post(self, endpoint: str, payload: dict) -> dict:
    await asyncio.sleep(0.35)       # ~3 req/s, Fakturoid limit je vyšší
    resp = await self._client.post(endpoint, json=payload)
    if resp.status_code == 429:
        await asyncio.sleep(5)
        resp = await self._client.post(endpoint, json=payload)
    resp.raise_for_status()
    return resp.json()
```

## CLI Interface

```bash
# Základní migrace — backup soubor jako první argument
f2f migrate firma.winstrom-backup \
  --fakturoid-slug  michal-manena \
  --fakturoid-token ft_••••••••••••

# Dry-run — zobraz co by se importovalo, nic neprovádí (výchozí chování)
f2f migrate firma.winstrom-backup --fakturoid-slug … --fakturoid-token …

# Reálný import vyžaduje explicitní potvrzení
f2f migrate firma.winstrom-backup --fakturoid-slug … --fakturoid-token … --yes

# Inspect zálohy — co záloha obsahuje (bez importu)
f2f inspect firma.winstrom-backup

# Import pouze konkrétní entity
f2f migrate firma.winstrom-backup … --only contacts
f2f migrate firma.winstrom-backup … --only issued-invoices
f2f migrate firma.winstrom-backup … --only received-invoices
```

Pokud `--fakturoid-token` chybí, CLI se zeptá interaktivně (`typer.prompt(hide_input=True)`).
Token se nikdy neukládá na disk. Alternativně přes env proměnnou `FAKTUROID_TOKEN`.

## Dev Guidelines

Viz [CLAUDE.md](../CLAUDE.md) pro plné instrukce pro AI agenty. Shrnutí:

- **Backup soubor je v `.gitignore`** — obsahuje účetní data, nesmí být commitován.
- **`f2f inspect` je nejlepší přítel** — ověř strukturu tabulky před psaním mapperu.
- **`--dry-run` je výchozí chování** — reálný import vyžaduje `--yes`.
- **Unit testy na mapování** — v `tests/fixtures/` jsou vzorové řádky (tuples/dicts), testy parseru
  a mapperu běží bez sítě a bez souboru zálohy.
- **Fakturoid sandbox** — použij testovací účet pro iteraci nad importem bez rizika ostrých dat.

## Phases

| Fáze | Název | Popis |
|---|---|---|
| 1 | Backup parser + inspect | `pyproject.toml`, CLI skeleton, `pgdumplib` wrapper nad klíčovými tabulkami. Výstup: `f2f inspect firma.winstrom-backup` zobrazí počty entit a vzorový záznam každého typu. |
| 2 | Kontakty → Fakturoid | Pydantic modely, mapper, httpx klient, import s deduplikací přes IČO. Dry-run výstup v tabulce. |
| 3 | Vydané faktury | Parser `ddoklfak`/`dpolfak` (modul=FAV), mapper, lookup kontaktů, import. Zachování číslování, validace součtů. |
| 4 | Přijaté faktury | Totéž pro modul=FAP, import přes `inbox_invoices` (ověřit endpoint). |
| 5 | Polish + open-source release | Edge cases (zahraniční faktury, různé DPH sazby, kontakty bez IČO, storno doklady, zálohové faktury), unit testy, README, GitHub release. |

## Open Questions

| # | Otázka | Jak ověřit | Stav |
|---|---|---|---|
| Q1 | Přesná struktura zálohy — formát, tabulky, sloupce | `f2f inspect` | ✅ **Vyřešeno** — je to `pg_dump -Fc`, ne ZIP+XML. Klíčové tabulky zdokumentovány výše. |
| Q2 | Fakturoid endpoint pro přijaté faktury — `inbox_invoices` nebo jiný? | Fakturoid API docs / sandbox test | Otevřeno |
| Q3 | Číselné řady ve Fakturoidu — lze importovat vlastní číslo faktury z FlexiBee? | Fakturoid API — pole `number` na invoice POST | Otevřeno |
| Q4 | Přijaté faktury — kompletní data v záloze (dodavatel, položky, částky)? | Inspect reálné zálohy | ✅ **Vyřešeno** — 726 řádků FAP v `ddoklfak`, položky v `dpolfak` propojené přes `iddoklfak` |
| Q5 | PDF přílohy k fakturám — zachovat nebo ignorovat? | Tabulky `wpriloha`/`wprilohadata` existují v záloze — obsahují binární data příloh | Otevřeno, mimo scope v0.1 migrace |
| Q6 | Zálohové faktury (`idtypdokl` = ZÁLOHA/ZDD) a dobropisy — migrovat jako běžné faktury, jinak, nebo vynechat? | Konzultace s uživatelem, ověření Fakturoid podpory dobropisů | Nové |
| Q7 | Institucionální kontakty (zdravotka, socialka, finanční úřad) v `aadresar` — migrovat jako běžné subjekty? | Konzultace s uživatelem | Nové |
| Q8 | Storno doklady (`storno = true`) — vynechat z migrace? | Konzultace s uživatelem | Nové |
| Q9 | Kódování `astaty.kod` — čisté ISO 3166-1 alpha-2, nebo FlexiBee specifický formát (pozorováno `XI` pro Severní Irsko)? | Projít číselník `astaty` v `f2f inspect` | Nové |

## Historie verzí

- **v0.1** — první návrh, počítal s FlexiBee REST API + Playwright browser automation.
- **v0.2** — backup-first přístup, ale mylně předpokládal, že `.winstrom-backup` je ZIP s Winstrom XML.
- **v0.3** (tento dokument) — opraveno na základě skutečné inspekce zálohy: PostgreSQL custom-format
  dump, čtený přes `pgdumplib`. Tech stack a field mapping aktualizovány na reálné názvy tabulek/sloupců.
