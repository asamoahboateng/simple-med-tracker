"""
exports.py - Save tables and reports to Excel (.xlsx), CSV and printable HTML.

openpyxl is imported only when an Excel export actually happens, so the app starts faster.
The PDF itself is produced by the report page (ui/report.py) from report_html().
"""

import csv
import html
from pathlib import Path

import logic


def _table(rows: list[dict], columns: list[tuple[str, str]]) -> list[list]:
    """Header row plus one list of values per row, in the given (key, header) column order."""
    return [[header for _, header in columns]] + [[row.get(key) for key, _ in columns]
                                                  for row in rows]


def _add_sheet(workbook, name: str, table: list[list]) -> None:
    """Write `table` to a new sheet and make column widths roughly fit their contents."""
    from openpyxl.utils import get_column_letter
    sheet = workbook.create_sheet(name)
    for values in table:
        sheet.append(values)
    for i, column in enumerate(zip(*table), start=1):
        longest = max(len("" if v is None else str(v)) for v in column)
        sheet.column_dimensions[get_column_letter(i)].width = min(max(10, longest + 2), 60)


def _save_workbook(sheets: dict[str, list[list]], path: Path) -> None:
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.remove(workbook.active)       # start without the default empty sheet
    for name, table in sheets.items():
        _add_sheet(workbook, name, table)
    workbook.save(path)


def export_table(rows: list[dict], columns: list[tuple[str, str]], path) -> Path:
    """Save rows to .xlsx or .csv, depending on the file extension."""
    path = Path(path)
    table = _table(rows, columns)
    if path.suffix.lower() == ".csv":
        # utf-8-sig lets Excel open the CSV with accents etc. displayed correctly
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(table)
    else:
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        _save_workbook({"Data": table}, path)
    return path


# Column definitions shared by the report page, Excel export and PDF.
REPORT_MEDICINE_COLUMNS = [
    ("rank", "Rank"), ("medicine", "Medicine"), ("dispensed", "Qty dispensed"),
    ("percent", "% of total"), ("received", "Qty received"),
    ("stock", "Current stock"), ("status", "Status"),
]
REPORT_PRESCRIBER_COLUMNS = [("prescriber", "Prescriber"), ("qty", "Total quantity"),
                             ("entries", "Entries")]
REPORT_DAY_COLUMNS = [("date", "Date"), ("qty", "Quantity dispensed")]


def summary_pairs(report: logic.PeriodReport) -> list[tuple[str, object]]:
    pairs = [
        ("Month" if report.is_month else "Period", report.title),
        ("Days counted", report.days_counted),
        ("Total dispensed", report.total_dispensed),
        ("Total stock received", report.total_received),
        ("Deliveries", report.deliveries),
        ("Dispensing entries", report.entry_count),
        ("Different medicines dispensed", report.medicines_dispensed),
        (f"Average dispensed per day ({report.days_counted} days)", report.avg_per_day),
    ]
    if report.change_vs_prev is not None:
        pairs.append((f"Per day compared with {report.prev_title}",
                      f"{report.change_vs_prev:+d}% ({report.prev_avg_per_day} per day)"))
    return pairs


def top_day_rows(report: logic.PeriodReport) -> list[dict]:
    return [{"date": d.isoformat(), "qty": q} for d, q in report.top_days]


def export_report_excel(report: logic.PeriodReport, path) -> Path:
    """Save the whole report (a month or a date range) to one Excel file with several sheets."""
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    _save_workbook({
        "Summary": [["Item", "Value"]] + [list(pair) for pair in summary_pairs(report)],
        "Medicines": _table(report.medicines, REPORT_MEDICINE_COLUMNS),
        "Top 10": _table(report.medicines[:10], REPORT_MEDICINE_COLUMNS[:4]),
        "Busiest days": _table(top_day_rows(report), REPORT_DAY_COLUMNS),
        "Prescribers": _table(report.prescribers, REPORT_PRESCRIBER_COLUMNS),
    }, path)
    return path


def _html_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p><i>No data for this period.</i></p>"
    head = "".join(f"<th align='left' bgcolor='#e8eef3'>{html.escape(h)}</th>"
                   for _, h in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r.get(k, '')))}</td>" for k, _ in columns)
        + "</tr>"
        for r in rows
    )
    return (f"<table border='1' cellspacing='0' cellpadding='4' width='100%'>"
            f"<tr>{head}</tr>{body}</table>")


def report_html(report: logic.PeriodReport, app_name: str, chart_src: str | None = None) -> str:
    """Printable HTML version of the report (used for the PDF)."""
    summary = "".join(f"<tr><td>{html.escape(k)}</td><td><b>{html.escape(str(v))}</b></td></tr>"
                      for k, v in summary_pairs(report))
    chart = f"<p><img src='{chart_src}' width='640'></p>" if chart_src else ""
    return f"""
    <html><body style='font-family: sans-serif; font-size: 10pt;'>
    <h2>{html.escape(app_name)} - Report: {html.escape(report.title)}</h2>
    <h3>Summary</h3>
    <table border='1' cellspacing='0' cellpadding='4'>{summary}</table>
    <h3>Top 10 medicines</h3>
    {chart}
    <h3>Medicines ranked by quantity dispensed</h3>
    {_html_table(report.medicines, REPORT_MEDICINE_COLUMNS)}
    <h3>Top 5 busiest days</h3>
    {_html_table(top_day_rows(report), REPORT_DAY_COLUMNS)}
    <h3>By prescriber</h3>
    {_html_table(report.prescribers, REPORT_PRESCRIBER_COLUMNS)}
    </body></html>
    """
