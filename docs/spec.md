# flexibee2fakturoid — Technická specifikace

> Stav: v0.6 — Fáze 1–4 a rollback implementované a end-to-end otestované proti mock Fakturoid serveru
> i proti reálné záloze (dry-run/mock, nikdy produkční účet). Před prvním ostrým `--yes` během zbývá
> ověřit Q2/Q3 proti reálnému Fakturoid API — viz Open Questions.
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
| `aadresar` | Kontakty (dodavatelé i odběratelé v jedné tabulce) | 615 řádků v testovací záloze, ale jen **74 skutečných obchodních kontaktů** (`typvztahuk` = odběratel/dodavatel/oboje) — zbytek (541) jsou vestavěné referenční číselníky FlexiBee (finanční úřady, OSSZ pobočky, zdravotní pojišťovny), viz Field Mapping a Q7 |
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
│   ├── cli.py                 # typer entry point — inspect, migrate, rollback
│   ├── flexibee/
│   │   ├── backup.py          # pgdumplib wrapper, čtení tabulek + lookup_table()
│   │   └── models.py          # Pydantic: FlexContact, FlexInvoice, FlexInvoiceLine
│   ├── fakturoid/
│   │   ├── client.py          # httpx wrapper, rate limiting, retry, base-url override
│   │   └── models.py          # Pydantic: Subject, Invoice, InvoiceLine
│   └── migration/
│       ├── mapper.py          # FlexiBee → Fakturoid překlad polí + dedup plánování
│       ├── runner.py          # orchestrace, dry-run report, apply, rollback
│       └── run_log.py         # perzistence vytvořených záznamů pro rollback
└── tests/
    ├── fixtures/               # vzorové řádky/tabulky pro unit testy (bez reálné zálohy)
    ├── mock_fakturoid/         # stavový Flask mock Fakturoid API pro e2e testy
    │   ├── app.py
    │   └── server.py           # spouští app.py na reálném lokálním socketu
    ├── conftest.py
    ├── test_backup.py
    ├── test_models.py
    ├── test_mock_fakturoid.py
    ├── test_e2e_migrate.py     # e2e: kontakty
    ├── test_e2e_invoices.py    # e2e: vydané/přijaté faktury, --since/--until
    └── test_e2e_rollback.py    # e2e: rollback
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
| `stavuhrk` (vyplněno = zaplaceno, hodnota pozorována: `stavUhr.uhrazenoRucne`) | stav úhrady (endpoint/pole ověřit — Fakturoid má koncept "zaplaceno" na faktuře) | **Core mapping, ne edge case.** Bez tohohle budou všechny historické faktury ve Fakturoidu vypadat jako nezaplacené hned po importu. Opraveno oproti dřívějšímu draftu — `datuhr` existuje taky (datum úhrady), ale `stavuhrk` je přímější signál "zaplaceno/nezaplaceno" |
| `idmeny` (FK → `umeny.kod`) | `currency` | **Core mapping, ne edge case.** ~~`mena`~~ — tenhle sloupec v reálném schématu neexistuje, oprava oproti dřívějšímu draftu. Pozorováno v datech: 985× CZK, 64× EUR |
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

**Dedup se nedělá per-record GET dotazem** (viz API limity níže — při 1664+ záznamech by to samo
o sobě spotřebovalo většinu měsíčního rozpočtu requestů). Místo toho runner na začátku migrace
jednou stáhne **kompletní seznam** existujících subjektů a faktur (paginované `GET`), postaví si
lokální in-memory index (`registration_no → subject_id`, `number → invoice_id`) a dedup kontroluje
proti němu. Teprve nový/neexistující záznam vede k `POST`. Bezpečné pro opakované spuštění.

### API limity a rozpočet requestů

Tarif **Zdarma / Na lehko**: **1500 API požadavků / kalendářní měsíc.** Limit je měkký — Fakturoid
při jednorázovém překročení (do 15 000 požadavků) nic neúčtuje ani neomezuje, opakované překračování
doporučí vyšší tarif. (Zdroj: nastavení účtu autora, ověřeno 2026-07-19.)

Reálná záloha obsahuje ~74 skutečných kontaktů (viz Field Mapping — 541 z 615 řádků `aadresar` jsou
vestavěné referenční číselníky, vynechané z migrace) + 323 vydaných + 726 přijatých faktur =
**~1123 záznamů k vytvoření.** I s dedup přes lokální index (pár desítek `GET` na stažení seznamů, ne
stovky) se samotné `POST` požadavky na vytvoření pohybují blízko měsíčního limitu volného tarifu.
Číselné položky faktur (`dpolfak`) jdou většinou v těle `POST` na fakturu, ne jako samostatný request
— ověřit v Fakturoid API docs, jestli náhodou nejde o zvláštní endpoint per položka (to by rozpočet
výrazně prodražilo).

Praktické důsledky:
- **Naivní "GET před každým POST" dedup je mimo rozpočet** — proto cachovaný index výše, ne volitelná optimalizace.
- Opakované `--dry-run` iterace během ladění taky spotřebovávají budget (stahují seznamy pro report) — počítat s tím při iterování, nezkoušet to donekonečna ve stejném měsíci.
- Jednorázové mírné překročení limitu při finálním produkčním běhu je dle vlastní politiky Fakturoidu v pořádku a nic nestojí — není důvod kvůli tomu předplácet vyšší tarif jen na jednorázovou migraci.
- `f2f rollback` (mazání) spotřebovává requesty stejně jako import — dalších až ~1664 při plném rollbacku. Neplýtvat: rollback zavolat, jen když je to skutečně potřeba.

### Žádné explicitní odesílání

Ověřeno v nastavení Fakturoid účtu autora: `POST` na vytvoření faktury/kontaktu **sám o sobě
neodesílá žádný email.** Odeslání faktury zákazníkovi je samostatná, explicitní akce —
`POST .../invoices/{id}/send_by_email.json` (šablony "Nová faktura", upomínky atd. se odesílají jen
ručně nebo tímhle voláním, ne jako vedlejší efekt vytvoření záznamu).

<div style="border-left:3px solid firebrick;padding-left:1em">
<strong>Tvrdé pravidlo</strong><br>
Migrační kód nikdy nevolá <code>send_by_email.json</code> ani žádný jiný explicitní send/notify
endpoint. Import stovek historických faktur by jinak reálným zákazníkům a dodavatelům rozeslal
stovky nechtěných emailů o letitých fakturách.
</div>

### Rate limiting

```python
async def _post(self, endpoint: str, payload: dict) -> dict:
    await asyncio.sleep(0.35)       # per-request throttling, ochrana proti 429
    resp = await self._client.post(endpoint, json=payload)
    if resp.status_code == 429:
        await asyncio.sleep(5)
        resp = await self._client.post(endpoint, json=payload)
    resp.raise_for_status()
    return resp.json()
```

`429` (krátkodobý rate limit na request/s) a měsíční kvóta 1500 požadavků jsou **dva různé limity** —
retry logika výše řeší jen ten první. Vyčerpání měsíční kvóty se neprojeví jako `429` retryovatelný
requestem znovu za pár vteřin; runner by měl takový stav rozpoznat (chybová odpověď API při
vyčerpané kvótě) a migraci čitelně zastavit s reportem "hotovo X z Y", ne slepě zkoušet dál donekonečna.

<a id="cutover-strategie-postupný-import"></a>
## Cutover strategie: postupný import

Rozhodnuto: první produkční běh se **omezí na faktury z aktuálního roku**, historie se doimportuje
postupně později. Reálná čísla ze zálohy (2026-07-19):

| Rok | Vydané (FAV) | Přijaté (FAP) | Celkem |
|---|---|---|---|
| **2026 (první běh)** | 6 | 39 | **45** |
| 2011–2025 (backfill) | 317 | 687 | 1004 |

Letošní dávka odkazuje jen na **9 unikátních kontaktů** (z 74 skutečných obchodních kontaktů — viz
Field Mapping a Q7 k vestavěným číselníkům FlexiBee, které se z migrace vynechávají).

### Proč

- Dramaticky menší blast radius prvního ostrého běhu — 45 záznamů, ne 1049.
- API rozpočet přestává být problém pro cutover samotný (45 faktur ≪ 1500/měsíc). Historický
  backfill zůstává tam, kde ho dokumentuje [API limity a rozpočet requestů](#api-limity-a-rozpočet-requestů) —
  řeší se až později, klidně rozložený přes víc měsíců.
- Menší dávka = rychlejší a levnější první ověření, že mapper/číslování/stav úhrady fungují správně
  na reálném účtu, než se pustí do zbytku historie.
- Idempotentní dedup (viz [Idempotence](#idempotence)) dělá z opakovaných/rozšiřovaných běhů bezpečnou
  operaci — pozdější běh s dřívějším `--since` naimportuje jen to, co ještě neexistuje, nic
  nezdupluje.

### Rozsah filtru

**Kontakty se importují vždy celé** (74 skutečných obchodních kontaktů, nezávisle na období faktur —
vestavěné číselníky finančních úřadů/OSSZ/zdravotních pojišťoven se vynechávají by default, viz Q7) —
nízkoriziková adresářová data, chceš mít kompletní seznam pro fakturaci komukoliv od začátku. Jen
**faktury** (vydané i přijaté) se filtrují podle `datvyst` přes `--since`/`--until` (viz CLI Interface
níže).

### Doporučený postup backfillu

1. `--since <letos-01-01>` — cutover, ověření na malé dávce
2. Po ověření: postupně `--since 2025-01-01 --until 2026-01-01`, pak `2024`, atd. — nebo rovnou
   `--since 2011-01-01` na celou historii najednou, pokud po cutoveru není důvod dávkovat dál
3. Každý běh nezávisle podléhá stejnému `--dry-run` → `--yes` postupu a run logu/rollbacku
   (viz [Rollback & Failure Recovery](#rollback--failure-recovery))

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

# Faktury omezené na časové okno (datvyst) — cutover na aktuální rok, historie později
# --since/--until se týká jen faktur, kontakty se importují vždy celé
f2f migrate firma.winstrom-backup … --since 2026-01-01
f2f migrate firma.winstrom-backup … --since 2025-01-01 --until 2026-01-01   # postupný backfill po letech

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
| 3 | Vydané faktury | Parser `ddoklfak`/`dpolfak` (modul=FAV), mapper, lookup kontaktů, `--since`/`--until` filtr, import. Zachování číslování, stav úhrady, měna, validace součtů. První ostrý běh omezen na aktuální rok (viz [Cutover strategie](#cutover-strategie-postupný-import)), historie doimportována postupně později. |
| 4 | Přijaté faktury | Totéž pro modul=FAP, import přes `inbox_invoices` (ověřit endpoint). Stejný `--since`/`--until` cutover přístup jako Fáze 3. |
| 5 | Polish + wrap-up | Edge cases (různé DPH sazby, kontakty bez IČO, storno doklady, zálohové faktury), unit testy, README. Měna a stav úhrady jsou core mapping od Fáze 3, ne edge case zde. Kód zůstává veřejný na GitHubu jako inspirace, ne jako udržovaný OSS projekt — bez ambice podporovat cizí FlexiBee instalace (viz [Publikum a rozsah](#publikum-a-rozsah)). |
| — | PDF přílohy faktur (#9) | Ex-post, nezávisle na ostatních fázích — provede se až po dokončení core migrace (cutover + historický backfill, #8). Ne mission-critical, nemá číslo fáze, protože neblokuje ani není blokováno ničím výše. |

## Open Questions

| # | Otázka | Jak ověřit | Stav |
|---|---|---|---|
| Q1 | Přesná struktura zálohy — formát, tabulky, sloupce | `f2f inspect` | ✅ **Vyřešeno** — je to `pg_dump -Fc`, ne ZIP+XML. Klíčové tabulky zdokumentovány výše. |
| Q2 | Fakturoid endpoint pro přijaté faktury — `inbox_invoices` nebo jiný? | Fakturoid API docs / sandbox test | Otevřeno |
| Q3 | Číselné řady ve Fakturoidu — lze importovat vlastní číslo faktury z FlexiBee? | `GET /accounts/{slug}/number_formats.json` vrací seznam číselných řad s `id`, který se používá při tvorbě dokladu — potvrzuje, že *vlastní řadu* si lze zvolit/vytvořit. Neověřeno: jde nastavit i konkrétní historické `number` přímo na jednom dokladu (mimo automatickou řadu), nebo číselná řada jen určuje vzor pro *budoucí* automatické číslování? Rozhodující test před Fází 3. | 🟡 Částečně objasněno |
| Q4 | Přijaté faktury — kompletní data v záloze (dodavatel, položky, částky)? | Inspect reálné zálohy | ✅ **Vyřešeno** — 726 řádků FAP v `ddoklfak`, položky v `dpolfak` propojené přes `iddoklfak` |
| Q5 | PDF přílohy k fakturám — zachovat nebo ignorovat? | Tabulky `wpriloha`/`wprilohadata` existují v záloze — obsahují binární data příloh | 🟢 **Rozhodnuto** — ano, zachovat, ale ex-post po dokončení core migrace (#9), ne mission-critical a ne blokující |
| Q6 | Zálohové faktury (`idtypdokl` = ZÁLOHA/ZDD) a dobropisy — migrovat jako běžné faktury, jinak, nebo vynechat? | Konzultace s uživatelem, ověření Fakturoid podpory dobropisů | Nové |
| Q7 | Institucionální kontakty (zdravotka, socialka, finanční úřad) v `aadresar` — migrovat jako běžné subjekty? | `f2f migrate --fakturoid-slug … --fakturoid-token …` (dry-run) na reálné záloze | 🟢 **Rozhodnuto (implementace)** — vynechány by default. Skutečná distribuce: 442× `financniUrad`, 89× `socialka`, 10× `zdravotka` (541 z 615 řádků — vestavěné číselníky FlexiBee, ne obchodní vztahy vytvořené uživatelem). Přepínatelné přes `--include-institutional-contacts`, pokud se ukáže, že je uživatel přece jen chce. |
| Q8 | Storno doklady (`storno = true`) — vynechat z migrace? | Konzultace s uživatelem | Nové |
| Q9 | Kódování `astaty.kod` — čisté ISO 3166-1 alpha-2, nebo FlexiBee specifický formát (pozorováno `XI` pro Severní Irsko)? | Projít číselník `astaty` v `f2f inspect` | Nové |

## Historie verzí

- **v0.1** — první návrh, počítal s FlexiBee REST API + Playwright browser automation.
- **v0.2** — backup-first přístup, ale mylně předpokládal, že `.winstrom-backup` je ZIP s Winstrom XML.
- **v0.3** — opraveno na základě skutečné inspekce zálohy: PostgreSQL custom-format
  dump, čtený přes `pgdumplib`. Tech stack a field mapping aktualizovány na reálné názvy tabulek/sloupců.
  Přidána Testing Strategy (mock Fakturoid API), Rollback & Failure Recovery a přerámování na osobní
  nástroj (kód veřejný jako inspirace, ne udržovaný OSS projekt).
- **v0.4** — doplněno o reálná zjištění z Fakturoid účtu autora: měsíční API limit
  1500 requestů na volném tarifu (a jeho měkká politika při překročení), potvrzení že `POST` na
  vytvoření záznamu neodesílá email automaticky (tvrdé pravidlo: nikdy nevolat `send_by_email.json`),
  a detail k `number_formats.json` pro Q3 (číselné řady).
- **v0.5** — rozhodnuto o postupném cutoveru: první produkční běh omezen na faktury
  aktuálního roku (`--since`/`--until` filtr na `datvyst`), historie (1004 z 1049 faktur) se
  doimportuje postupně později. Kontakty zůstávají plný import (74 skutečných obchodních kontaktů,
  nezávisle na období faktur — z 615 řádků v `aadresar` jich 541 jsou vestavěné číselníky FlexiBee,
  vynechané by default, viz Q7).
- **v0.6** (tento dokument) — Fáze 1–4 a rollback implementované (`f2f inspect`/`migrate`/`rollback`),
  end-to-end otestované proti mock Fakturoid serveru i proti reálné záloze. Reálné testování odhalilo
  a opravilo: `dpolfak.nazev` může být `NULL` (mapper má fallback), `--only`/`--since`/`--until`
  fungují přesně dle plánu (letošní dávka: 6 vydaných + 39 přijatých, sedí s dřívějším odhadem).
  Q2 a Q3 zůstávají neověřené proti živému Fakturoid API — implementováno podle nejlepšího odhadu,
  nutno ověřit na sandboxu před prvním produkčním `--yes` během.
