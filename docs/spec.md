# flexibee2fakturoid — Technická specifikace

> Stav: Draft v0.3 — backup-first přístup, ověřeno proti reálné záloze.
> Nahrazuje artefakt v0.2, který předpokládal jiný formát zálohy (viz [Historie](#historie-verzí) níže).

## Publikum a rozsah

Tento nástroj je primárně pro osobní použití autora — migrace jeho vlastní firmy z FlexiBee do
Fakturoidu. Kód je veřejný na GitHubu **jako inspirace pro ostatní**, ne jako udržovaný open-source
projekt s očekáváním community podpory, issues od cizích uživatelů nebo záruky, že bude fungovat na
jiné FlexiBee instalaci (jiné moduly, jiná verze schématu, jiné customizace).

Praktický důsledek: **nestavíme robustnost proti neznámému schématu jiných firem.** Ověřujeme a
optimalizujeme pro strukturu, kterou vidíme v reálné záloze autora (viz [Backup formát](#backup-formát-winstrom-backup---skutečný-formát)).
Přesto zůstává v plné vážnosti vše, co se týká **bezpečnosti vlastních účetních dat** — dry-run,
idempotence, e2e testy proti mocku, rollback (viz níže) — protože tady jde o data jednoho člověka bez
komunity, která by chybu odhalila dřív než on sám na ostrém účtu.

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
    ├── mock_fakturoid/         # stavový Flask mock Fakturoid API pro e2e testy
    │   └── app.py
    ├── test_mapper.py
    └── test_e2e_migrate.py    # end-to-end testy CLI proti mock_fakturoid
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

# Přepsání base URL Fakturoid API — použito testy (mock server), jinak vždy produkční API
f2f migrate firma.winstrom-backup … --fakturoid-base-url http://127.0.0.1:8000

# Vrátit zpět přesně to, co vytvořil daný běh migrace (viz Rollback & Failure Recovery)
f2f rollback <run-id> --fakturoid-slug … --fakturoid-token …
```

Pokud `--fakturoid-token` chybí, CLI se zeptá interaktivně (`typer.prompt(hide_input=True)`).
Token se nikdy neukládá na disk. Alternativně přes env proměnnou `FAKTUROID_TOKEN`.

`--fakturoid-base-url` existuje výhradně proto, aby šel `fakturoid/client.py` nasměrovat na lokální
mock server v testech (viz [Testing Strategy](#testing-strategy)) — v produkčním použití se nikdy
nenastavuje.

## Dev Guidelines

Viz [CLAUDE.md](../CLAUDE.md) pro plné instrukce pro AI agenty. Shrnutí:

- **Backup soubor je v `.gitignore`** — obsahuje účetní data, nesmí být commitován.
- **`f2f inspect` je nejlepší přítel** — ověř strukturu tabulky před psaním mapperu.
- **`--dry-run` je výchozí chování** — reálný import vyžaduje `--yes`.
- **Unit testy na mapování** — v `tests/fixtures/` jsou vzorové řádky (tuples/dicts), testy parseru
  a mapperu běží bez sítě a bez souboru zálohy.
- **End-to-end testy proti mock Fakturoid API** — celý `migrate` flow se testuje proti lokálnímu
  mock serveru, nikdy proti reálnému účtu ani sandboxu v CI. Viz [Testing Strategy](#testing-strategy).
- **Fakturoid sandbox** — reálný testovací účet Fakturoidu slouží jen k ruční, jednorázové verifikaci
  před releasem (ověření skutečného API chování, ne automatizované CI testy).

<a id="testing-strategy"></a>
## Testing Strategy

Projekt pracuje s reálnými účetními daty a zapisuje do ostrého účetního systému uživatele (Fakturoid).
Proto testování má dvě oddělené úrovně a ani jedna se nesmí spoléhat na reálný Fakturoid účet:

### 1. Unit testy (parser, mapper)

- `tests/fixtures/` — syntetické řádky/tuples reprezentující výstup `pgdumplib` pro `aadresar`,
  `ddoklfak`, `dpolfak`, `dtypdokl`, `astaty`. Žádný reálný `.winstrom-backup` v repu.
- Testují čistou logiku: parsing sloupců, mapper FlexiBee → Fakturoid pole, edge cases (chybějící
  IČO, cizí měna, storno příznak).
- Běží bez sítě, bez souboru zálohy, v milisekundách.

### 2. End-to-end testy proti mock Fakturoid API

Nestačí unit test mapperu — potřebujeme ověřit **celý** tok `migrate` (CLI → httpx klient → HTTP →
zpracování odpovědi → idempotence/dedup → report), aniž by šlo o reálný Fakturoid účet. K tomu slouží
vlastní mock server, ne mockování na úrovni Python funkcí:

- `tests/mock_fakturoid/` — malý, stavový HTTP server (Flask, dev-only závislost; běžící lokálně na
  `127.0.0.1`, náhodný volný port), který implementuje relevantní subset Fakturoid REST API v3 podle
  [oficiální dokumentace](https://www.fakturoid.cz/api/v3):
  - `POST /accounts/{slug}/subjects.json` + `GET .../subjects.json?registration_no=…` (dedup lookup)
  - `POST /accounts/{slug}/invoices.json` + `GET .../invoices.json?number=…`
  - `POST /accounts/{slug}/inbox_invoices.json` (endpoint potvrdit dle Q2)
  - Autentizace: kontrola Bearer tokenu, `401` při chybě
  - Validace povinných polí — `422` s tělem podobným reálné Fakturoid chybové odpovědi
  - Simulace `429 Too Many Requests` (např. každý N-tý request), aby se ověřila retry logika klienta
  - Stav (vytvořené subjekty/faktury) drženy v paměti po dobu běhu test session — umožňuje ověřit
    idempotenci (druhé spuštění migrace nic nevytvoří duplicitně)
- Pytest fixture spustí server na pozadí (vlákno nebo `multiprocessing`) před testem a ukončí po něm.
- CLI se v těchto testech spouští s `--fakturoid-base-url` směřujícím na mock, přes `CliRunner`
  (typer) nebo subprocess — reálný network stack (httpx, retry, serializace JSON) se skutečně
  provolá, jen proti localhost místo `app.fakturoid.cz`.
- Tyto testy běží v CI na každý PR, bez nutnosti jakýchkoli reálných credentials.

### Co e2e testy proti mocku ověřují

- Kontakt s duplicitním IČO se podruhé nevytvoří (idempotence)
- Faktura zachovává číslo z FlexiBee (`number` v requestu odpovídá `kod`)
- `--dry-run` (výchozí) nikdy neprovede žádný `POST` na mock server
- Retry po `429` proběhne a request nakonec uspěje
- Neplatný/chybějící token vede k čitelné chybové hlášce, ne pádu s tracebackem
- Report na konci migrace odpovídá počtu skutečně vytvořených/přeskočených záznamů na mock serveru

### Co mock nenahrazuje

Mock je zjednodušená implementace — nezachytí každou libovolnost reálného Fakturoid API (limity,
edge cases validace, chování `inbox_invoices`). Před prvním ostrým (produkčním) během proto zůstává
**jeden ruční** ověřovací běh proti reálnému Fakturoid sandbox účtu — mimo automatizované testy,
dělá ho člověk.

<a id="rollback--failure-recovery"></a>
## Rollback & Failure Recovery

Migrace zapisuje do ostrého účetnictví. "Smaž všechno ve Fakturoidu a spusť znovu" **není bezpečná
univerzální odpověď** na chybu — bezpečnost závisí na tom, jestli uživatel mezitím ve Fakturoidu
s daty už pracoval (nová faktura, označení jako zaplaceno, odeslaná upomínka). Slepý wipe by smazal
i tuhle reálnou práci, ne jen to, co vytvořila migrace.

Dedup logika (IČO / číslo faktury) navíc chrání jen proti **duplicitám** při opakovaném běhu — pokud
je bug v tom, že se vytvořil *špatný* záznam (špatná DPH sazba, částka), opravený skript ho při
dalším běhu přeskočí jako "už existuje", nezmění ho. Idempotence ≠ oprava.

### Run log

Každý reálný (`--yes`) běh migrace persistuje lokální run log (`~/.f2f/runs/<run-id>.json` nebo
podobně, mimo git repo) se záznamem pro každý vytvořený objekt: FlexiBee zdrojové ID, Fakturoid ID,
typ entity, časová značka, run ID. Bez tohohle nejde bezpečně smazat "jen to, co vytvořila migrace"
jinak než ručně v UI záznam po záznamu — u stovek položek nepoužitelné a riskantní (smažeš i něco
cizího).

### `f2f rollback <run-id>`

Vlastní CLI příkaz, ne ruční úklid v UI. Načte run log daného běhu a smaže přesně ty záznamy, které
ten běh vytvořil, přes Fakturoid API (s rate limitingem jako import). Hlásí, co se smazat nepovedlo
(další bezpečný retry, ne tichý fail). Dělá z "wipe a zkusit znovu" bezpečnou jednopříkazovou operaci
— pokud je pořád co bezpečně smazat (viz tabulka níže).

### Postup podle situace

| Situace | Postup |
|---|---|
| Chyba nalezena při dry-run | Nic se nestalo, oprav a spusť znovu |
| Chyba po `--yes` na **sandboxu** | `f2f rollback <run-id>`, oprav, spusť znovu — bez rizika |
| Chyba po `--yes` na produkci, ve Fakturoidu mezitím nikdo nic nedělal | `f2f rollback <run-id>`, oprav, spusť znovu |
| Chyba po `--yes` na produkci, uživatel už s daty pracoval | Rollback celého běhu je mimo hru. Přes run log dohledat konkrétní postižené záznamy a opravit cíleně (update existujícího záznamu ve Fakturoidu), ne smazat/znovu vytvořit |

### Praktické pravidlo

Produkční `--yes` běh je **jednorázová událost**, ne iterační smyčka. Veškeré ladění mapperu se
odehrává na sandboxu a přes dry-run report, dokud čísla nesedí na 100 %. Produkční běh proběhne
jednou, s rollbackem jako safety netem pro případ, že se přesto něco najde hned potom — dokud ve
Fakturoidu ještě nikdo nezačal reálně pracovat.

## Phases

| Fáze | Název | Popis |
|---|---|---|
| 1 | Backup parser + inspect | `pyproject.toml`, CLI skeleton, `pgdumplib` wrapper nad klíčovými tabulkami. Výstup: `f2f inspect firma.winstrom-backup` zobrazí počty entit a vzorový záznam každého typu. |
| 2 | Kontakty → Fakturoid | Pydantic modely, mapper, httpx klient, import s deduplikací přes IČO. Dry-run výstup v tabulce. |
| 3 | Vydané faktury | Parser `ddoklfak`/`dpolfak` (modul=FAV), mapper, lookup kontaktů, import. Zachování číslování, validace součtů. |
| 4 | Přijaté faktury | Totéž pro modul=FAP, import přes `inbox_invoices` (ověřit endpoint). |
| 5 | Polish + wrap-up | Edge cases (zahraniční faktury, různé DPH sazby, kontakty bez IČO, storno doklady, zálohové faktury), unit testy, README. Kód zůstává veřejný na GitHubu jako inspirace, ne jako udržovaný OSS projekt — bez ambice podporovat cizí FlexiBee instalace (viz [Publikum a rozsah](#publikum-a-rozsah)). |

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
