"""
exports.py - Save tables and reports to Excel (.xlsx), CSV and printable HTML.

pandas is imported only when an export actually happens, so the app starts faster.
The PDF itself is produced by the report page (ui/report.py) from report_html().
"""

import html
from pathlib import Path

import logic


def _dataframe(rows: list[dict], columns: list[tuple[str, str]]):
    """Build a DataFrame with the given (key, header) columns, in that order."""
    import pandas as pd
    return pd.DataFrame([[row.get(key) for key, _ in columns] for row in rows],
                        columns=[header for _, header in columns])


def _autofit(worksheet, df) -> None:
    """Make Excel column widths roughly fit their contents."""
    from openpyxl.utils import get_column_letter
    for i, col in enumerate(df.columns, start=1):
        longest = max([len(str(col))] + [len(str(v)) for v in df[col].tolist()])
        worksheet.column_dimensions[get_column_letter(i)].width = min(max(10, longest + 2), 60)


def export_table(rows: list[dict], columns: list[tuple[str, str]], path) -> Path:
    """Save rows to .xlsx or .csv, depending on the file extension."""
    path = Path(path)
    df = _dataframe(rows, columns)
    if path.suffix.lower() == ".csv":
        # utf-8-sig lets Excel open the CSV with accents etc. displayed correctly
        df.to_csv(path, index=False, encoding="utf-8-sig")
    else:
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        import pandas as pd
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)
            _autofit(writer.sheets["Data"], df)
    return path


# Column definitions shared by the report page, Excel export and PDF.
REPORT_MEDICINE_COLUMNS = [
    ("rank", "Rank"), ("medicine", "Medicine"), ("dispensed", "Qty dispensed"),
    ("percent", "% of month"), ("received", "Qty received"),
    ("stock", "Current stock"), ("status", "Status"),
]
REPORT_PRESCRIBER_COLUMNS = [("prescriber", "Prescriber"), ("qty", "Total quantity"),
                             ("entries", "Entries")]
REPORT_DAY_COLUMNS = [("date", "Date"), ("qty", "Quantity dispensed")]


def summary_pairs(report: logic.MonthlyReport) -> list[tuple[str, object]]:
    return [
        ("Month", report.title),
        ("Total dispensed", report.total_dispensed),
        ("Total stock received", report.total_received),
        ("Dispensing entries", report.entry_count),
        ("Different medicines dispensed", report.medicines_dispensed),
        (f"Average dispensed per day ({report.days_counted} days)", report.avg_per_day),
    ]


def top_day_rows(report: logic.MonthlyReport) -> list[dict]:
    return [{"date": d.isoformat(), "qty": q} for d, q in report.top_days]


def export_report_excel(report: logic.MonthlyReport, path) -> Path:
    """Save the whole monthly report to one Excel file with several sheets."""
    import pandas as pd
    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    sheets = {
        "Summary": pd.DataFrame(summary_pairs(report), columns=["Item", "Value"]),
        "Medicines": _dataframe(report.medicines, REPORT_MEDICINE_COLUMNS),
        "Top 10": _dataframe(report.medicines[:10], REPORT_MEDICINE_COLUMNS[:4]),
        "Busiest days": _dataframe(top_day_rows(report), REPORT_DAY_COLUMNS),
        "Prescribers": _dataframe(report.prescribers, REPORT_PRESCRIBER_COLUMNS),
    }
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            _autofit(writer.sheets[name], df)
    return path


def _html_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "<p><i>No data for this month.</i></p>"
    head = "".join(f"<th align='left' bgcolor='#e8eef3'>{html.escape(h)}</th>"
                   for _, h in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r.get(k, '')))}</td>" for k, _ in columns)
        + "</tr>"
        for r in rows
    )
    return (f"<table border='1' cellspacing='0' cellpadding='4' width='100%'>"
            f"<tr>{head}</tr>{body}</table>")


def report_html(report: logic.MonthlyReport, app_name: str, chart_src: str | None = None) -> str:
    """Printable HTML version of the monthly report (used for the PDF)."""
    summary = "".join(f"<tr><td>{html.escape(k)}</td><td><b>{html.escape(str(v))}</b></td></tr>"
                      for k, v in summary_pairs(report))
    chart = f"<p><img src='{chart_src}' width='640'></p>" if chart_src else ""
    return f"""
    <html><body style='font-family: sans-serif; font-size: 10pt;'>
    <h2>{html.escape(app_name)} - Monthly report: {html.escape(report.title)}</h2>
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
