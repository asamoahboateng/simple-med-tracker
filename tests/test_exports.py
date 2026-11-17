"""Excel and CSV exports: headers, values, column order and sheet names."""

import csv

from openpyxl import load_workbook

import exports
import logic
from tests.conftest import TODAY

COLUMNS = [("medicine", "Medicine"), ("quantity", "Quantity"), ("note", "Note")]
ROWS = [
    {"medicine": "Paracetamol", "quantity": 100, "note": "Ça va", "extra": "ignored"},
    {"medicine": "Ibuprofen", "quantity": 5, "note": None},
]


def test_csv_export(tmp_path):
    saved = exports.export_table(ROWS, COLUMNS, tmp_path / "log.csv")
    raw = saved.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")          # BOM so Excel reads accents correctly
    with saved.open(encoding="utf-8-sig", newline="") as f:
        assert list(csv.reader(f)) == [
            ["Medicine", "Quantity", "Note"],
            ["Paracetamol", "100", "Ça va"],
            ["Ibuprofen", "5", ""],
        ]


def test_excel_export_keeps_numbers_as_numbers(tmp_path):
    saved = exports.export_table(ROWS, COLUMNS, tmp_path / "log")   # extension added
    assert saved.suffix == ".xlsx"
    sheet = load_workbook(saved)["Data"]
    assert [[c.value for c in row] for row in sheet.iter_rows()] == [
        ["Medicine", "Quantity", "Note"],
        ["Paracetamol", 100, "Ça va"],
        ["Ibuprofen", 5, None],
    ]
    assert sheet.column_dimensions["A"].width >= len("Paracetamol")


def test_excel_export_with_no_rows(tmp_path):
    saved = exports.export_table([], COLUMNS, tmp_path / "empty.xlsx")
    sheet = load_workbook(saved)["Data"]
    assert [[c.value for c in row] for row in sheet.iter_rows()] == [["Medicine", "Quantity", "Note"]]


def test_report_excel_has_every_sheet(conn, add, give, tmp_path):
    add(qty=100)
    give(qty=10, on="2026-06-02", prescriber="Dr A")
    report = logic.monthly_report(conn, 2026, 6, today=TODAY)
    saved = exports.export_report_excel(report, tmp_path / "report.xlsx")

    book = load_workbook(saved)
    assert book.sheetnames == ["Summary", "Medicines", "Top 10", "Busiest days", "Prescribers"]
    summary = {r[0].value: r[1].value for r in book["Summary"].iter_rows(min_row=2)}
    assert summary["Total dispensed"] == 10
    medicines = [[c.value for c in row] for row in book["Medicines"].iter_rows()]
    assert medicines[0] == [h for _, h in exports.REPORT_MEDICINE_COLUMNS]
    assert medicines[1][1:3] == ["Paracetamol", 10]
    prescribers = [[c.value for c in row] for row in book["Prescribers"].iter_rows(min_row=2)]
    assert prescribers == [["Dr A", 10, 1]]
