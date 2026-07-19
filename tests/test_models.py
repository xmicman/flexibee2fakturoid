from __future__ import annotations

from datetime import date
from decimal import Decimal

from f2f.flexibee.models import FlexContact, FlexInvoice, FlexInvoiceLine


def test_flex_contact_from_row_ignores_unknown_columns() -> None:
    row = {
        "idfirmy": "101",
        "kod": "VZP",
        "nazev": "Všeobecná zdravotní pojišťovna",
        "ic": None,
        "dic": None,
        "email": "info@vzp.cz",
        "tel": None,
        "ulice": "Orlická 2020/4",
        "mesto": "Praha",
        "psc": "130 00",
        "idfastatu": None,
        "typvztahuk": "typVztahu.zdravotka",
        "poznam": "irrelevant column not in the model",
    }
    contact = FlexContact.from_row(row)
    assert contact.idfirmy == 101
    assert contact.nazev == "Všeobecná zdravotní pojišťovna"
    assert contact.idfastatu is None


def test_flex_invoice_resolves_types_from_raw_strings() -> None:
    row = {
        "iddoklfak": "890",
        "kod": "VF1-0009/2024",
        "modul": "FAV",
        "datvyst": "2024-09-30",
        "datsplat": "2024-10-14",
        "duzppuv": "2024-09-30",
        "idfirmy": "736",
        "varsym": "100092024",
        "sumcelkem": "177870.00",
        "idmeny": "31",
        "idtypdokl": "37",
        "storno": "f",
        "stavuhrk": None,
    }
    invoice = FlexInvoice.from_row(row)
    assert invoice.datvyst == date(2024, 9, 30)
    assert invoice.sumcelkem == Decimal("177870.00")
    assert invoice.storno is False
    assert invoice.is_paid is False


def test_flex_invoice_is_paid_when_stavuhrk_set() -> None:
    row = {
        "iddoklfak": "1",
        "kod": "F1",
        "modul": "FAP",
        "datvyst": "2024-01-01",
        "sumcelkem": "100.00",
        "storno": "f",
        "stavuhrk": "stavUhr.uhrazenoRucne",
    }
    invoice = FlexInvoice.from_row(row)
    assert invoice.is_paid is True


def test_flex_invoice_storno_true() -> None:
    row = {
        "iddoklfak": "2",
        "kod": "F2",
        "modul": "FAV",
        "datvyst": "2024-01-01",
        "sumcelkem": "0.00",
        "storno": "t",
    }
    invoice = FlexInvoice.from_row(row)
    assert invoice.storno is True


def test_flex_invoice_line_decimal_fields() -> None:
    row = {
        "iddoklfak": "890",
        "nazev": "Programování",
        "mnozmj": "10.000000",
        "cenamj": "1500.000000",
        "szbdph": "21.00",
    }
    line = FlexInvoiceLine.from_row(row)
    assert line.mnozmj == Decimal("10.000000")
    assert line.cenamj == Decimal("1500.000000")
    assert line.szbdph == Decimal("21.00")
