"""Generate multi-format sample financial documents (XLSX, TXT, CSV, JSON)
matching the synthetic financial filing dataset.
"""

import csv
import json
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_DIR = ROOT / "sample-documents"

XLSX_DIR = SAMPLE_DIR / "XLSX Documents"
TXT_DIR = SAMPLE_DIR / "TXT Documents"
CSV_DIR = SAMPLE_DIR / "CSV Documents"
JSON_DIR = SAMPLE_DIR / "JSON Documents"

for d in [XLSX_DIR, TXT_DIR, CSV_DIR, JSON_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def style_table(ws, start_row, headers, rows):
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    alt_fill = PatternFill(start_color="F2F5F9", end_color="F2F5F9", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    current_row = start_row + 1
    for r_idx, row in enumerate(rows):
        fill = alt_fill if r_idx % 2 == 1 else None
        for col_idx, val in enumerate(row, 1):
            cell = ws.cell(row=current_row, column=col_idx, value=val)
            cell.border = thin_border
            if fill:
                cell.fill = fill
            if isinstance(val, int | float):
                cell.alignment = Alignment(horizontal="right")
                if isinstance(val, float):
                    cell.number_format = "#,##0.00"
                else:
                    cell.number_format = "#,##0"
            else:
                cell.alignment = Alignment(horizontal="left")
        current_row += 1

    for col in ws.columns:
        max_len = max(len(str(c.value or "")) for c in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 14)


# --------------------------------------------------------------------------
# 1. Excel (XLSX) Documents
# --------------------------------------------------------------------------

def create_cascadia_xlsx():
    wb = openpyxl.Workbook()
    # Sheet 1: MD&A and Overview
    ws1 = wb.active
    ws1.title = "Filing Summary"
    ws1["A1"] = "CASCADIA ROBOTICS, INC. (NASDAQ: CSCD)"
    ws1["A1"].font = Font(name="Calibri", size=14, bold=True, color="1F4E78")
    ws1["A2"] = "Form 10-K Annual Report | Fiscal Year Ended December 31, 2024"
    ws1["A2"].font = Font(name="Calibri", size=11, italic=True)

    ws1["A4"] = "Item 7. Management's Discussion and Analysis (MD&A)"
    ws1["A4"].font = Font(name="Calibri", size=12, bold=True)
    summary_text = (
        "Total revenue was $1,842 million in fiscal year 2024, an increase of 18% "
        "compared with $1,561 million in fiscal year 2023. Gross margin was 54.2%, "
        "improving 260 basis points due to manufacturing scale efficiencies. Operating "
        "income was $312 million compared with $224 million in 2023. Net income was $241 "
        "million, or $1.87 per diluted share."
    )
    ws1["A5"] = summary_text
    ws1["A5"].alignment = Alignment(wrap_text=True)
    ws1.row_dimensions[5].height = 50
    ws1.column_dimensions["A"].width = 75

    key_metrics_headers = ["Metric", "FY2024 ($M)", "FY2023 ($M)", "YoY Change (%)"]
    key_metrics_data = [
        ["Total Revenue", 1842, 1561, "+18.0%"],
        ["Gross Profit", 998, 805, "+24.0%"],
        ["Gross Margin", "54.2%", "51.6%", "+260 bps"],
        ["Operating Income", 312, 224, "+39.3%"],
        ["Net Income", 241, 173, "+39.3%"],
        ["Diluted EPS ($)", 1.87, 1.36, "+37.5%"],
    ]
    style_table(ws1, start_row=8, headers=key_metrics_headers, rows=key_metrics_data)

    # Sheet 2: Segment Results
    ws2 = wb.create_sheet(title="Segment Performance")
    ws2["A1"] = "Reportable Segment Revenue & Operating Income"
    ws2["A1"].font = Font(name="Calibri", size=13, bold=True, color="1F4E78")
    segment_headers = ["Segment", "FY2024 Revenue ($M)", "FY2023 Revenue ($M)", "FY2024 Operating Income ($M)"]
    segment_data = [
        ["Industrial Automation", 1203, 967, 268],
        ["Consumer Robotics", 421, 398, 31],
        ["Field Services", 218, 196, 13],
        ["Total Consolidated", 1842, 1561, 312],
    ]
    style_table(ws2, start_row=3, headers=segment_headers, rows=segment_data)

    # Sheet 3: Balance Sheets
    ws3 = wb.create_sheet(title="Balance Sheet")
    ws3["A1"] = "Consolidated Balance Sheets (in thousands)"
    ws3["A1"].font = Font(name="Calibri", size=13, bold=True, color="1F4E78")
    bs_headers = ["Line Item", "December 31, 2024 ($)", "December 31, 2023 ($)"]
    bs_data = [
        ["Total current assets", 612400, 498150],
        ["Property, plant and equipment, net", 894200, 781300],
        ["Goodwill and intangible assets", 412000, 412000],
        ["Total assets", 2341800, 2014500],
        ["Total current liabilities", 341200, 298400],
        ["Long-term debt", 450000, 500000],
        ["Total liabilities", 891200, 898400],
        ["Total stockholders' equity", 1450600, 1116100],
        ["Total liabilities and equity", 2341800, 2014500],
    ]
    style_table(ws3, start_row=3, headers=bs_headers, rows=bs_data)

    wb.save(XLSX_DIR / "CASCADIA-10K-FY2024.xlsx")


def create_atlas_xlsx():
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Financial Overview"
    ws1["A1"] = "ATLAS SEMICONDUCTOR, INC. (NASDAQ: ATLS)"
    ws1["A1"].font = Font(name="Calibri", size=14, bold=True, color="1F4E78")
    ws1["A2"] = "Form 10-K Annual Report | Fiscal Year Ended December 31, 2024"
    ws1["A2"].font = Font(name="Calibri", size=11, italic=True)

    headers = ["Segment", "Period Revenue ($M)", "Prior-Year Revenue ($M)", "Operating Income ($M)"]
    rows = [
        ["Industrial Chips", 1342, 1098, 267],
        ["Automotive Systems", 524, 472, 79],
        ["Edge Computing", 280, 254, 40],
        ["Total", 2146, 1824, 386],
    ]
    style_table(ws1, start_row=5, headers=headers, rows=rows)

    ws2 = wb.create_sheet(title="Balance Sheet")
    ws2["A1"] = "Consolidated Balance Sheets (in thousands)"
    ws2["A1"].font = Font(name="Calibri", size=13, bold=True, color="1F4E78")
    bs_headers = ["Balance Sheet Item", "Dec 31, 2024", "Dec 31, 2023"]
    bs_data = [
        ["Total current assets", 741600, 622400],
        ["Total assets", 2684500, 2311800],
        ["Total current liabilities", 402700, 361900],
        ["Total liabilities", 918400, 812700],
        ["Total stockholders' equity", 1766100, 1499100],
    ]
    style_table(ws2, start_row=3, headers=bs_headers, rows=bs_data)
    wb.save(XLSX_DIR / "01_Atlas_Semiconductor_Inc.xlsx")


def create_meridian_xlsx():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Q2 Financial Statements"
    ws["A1"] = "MERIDIAN ENERGY STORAGE TECHNOLOGIES, INC. (NYSE: MEST)"
    ws["A1"].font = Font(name="Calibri", size=14, bold=True, color="1F4E78")
    ws["A2"] = "Form 10-Q Quarterly Report | For the Three Months Ended June 30, 2024"
    ws["A2"].font = Font(name="Calibri", size=11, italic=True)

    headers = ["Segment", "Q2 FY2024 Revenue ($M)", "Q2 FY2023 Revenue ($M)", "Q2 Operating Income ($M)"]
    rows = [
        ["Grid-Scale Storage", 387, 294, 74],
        ["Commercial & Industrial", 148, 126, 21],
        ["Software & Services", 52, 41, 14],
        ["Total Consolidated", 587, 461, 109],
    ]
    style_table(ws, start_row=5, headers=headers, rows=rows)
    wb.save(XLSX_DIR / "MERIDIAN-10Q-Q2FY2024.xlsx")


# --------------------------------------------------------------------------
# 2. Text (TXT) Documents
# --------------------------------------------------------------------------

def create_txt_files():
    # Cascadia TXT
    cascadia_txt = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
FORM 10-K

ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934
For the fiscal year ended December 31, 2024
Commission File Number: 001-39482

CASCADIA ROBOTICS, INC.
(Exact name of registrant as specified in its charter)
NASDAQ: CSCD

SYNTHETIC SAMPLE DOCUMENT. Cascadia Robotics is a fictional company and every figure below is invented for testing purposes. Prepared in accordance with U.S. GAAP.

<!-- page: 2 -->
PART I - ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS

OVERVIEW
Total revenue was $1,842 million in fiscal year 2024, an increase of 18% compared with $1,561 million in fiscal year 2023. Growth was driven primarily by the Industrial Automation segment, which benefited from strong customer demand for warehouse picking robots.

Gross margin was 54.2% in fiscal year 2024, compared with 51.6% in fiscal year 2023, representing an expansion of 260 basis points.

Operating income reached $312 million in fiscal year 2024, compared with $224 million in fiscal year 2023, reflecting a 39.3% increase despite an increase in R&D operating expenses.

Net income for fiscal year 2024 was $241 million, or $1.87 per diluted share, compared with $173 million, or $1.36 per diluted share, in fiscal year 2023.

<!-- page: 3 -->
SEGMENT RESULTS

Revenue and operating income by reportable segment for the years ended December 31, 2024 and 2023:

+-------------------------+---------------+---------------+-----------------------+
| Segment                 | FY24 Revenue  | FY23 Revenue  | FY24 Operating Income |
+-------------------------+---------------+---------------+-----------------------+
| Industrial Automation   | $1,203 M      | $967 M        | $268 M                |
| Consumer Robotics       | $421 M        | $398 M        | $31 M                 |
| Field Services          | $218 M        | $196 M        | $13 M                 |
+-------------------------+---------------+---------------+-----------------------+
| Total Consolidated      | $1,842 M      | $1,561 M      | $312 M                |
+-------------------------+---------------+---------------+-----------------------+

<!-- page: 4 -->
CONSOLIDATED BALANCE SHEETS
(in thousands, except share and per share data)

ASSETS                                         December 31, 2024    December 31, 2023
---------------------------------------------  -----------------    -----------------
Total current assets                                $   612,400          $   498,150
Property, plant and equipment, net                      894,200              781,300
Goodwill and intangible assets                          412,000              412,000
Total assets                                        $ 2,341,800          $ 2,014,500

LIABILITIES AND STOCKHOLDERS' EQUITY
Total current liabilities                           $   341,200          $   298,400
Long-term debt, less current portion                    450,000              500,000
Total liabilities                                   $   891,200          $   898,400
Total stockholders' equity                            1,450,600            1,116,100
Total liabilities and stockholders' equity          $ 2,341,800          $ 2,014,500

<!-- page: 5 -->
CONSOLIDATED STATEMENTS OF CASH FLOWS
Net cash provided by operating activities was $389 million in fiscal year 2024, compared with $298 million in fiscal year 2023. Capital expenditures were $142 million. Free cash flow was $247 million.
"""
    (TXT_DIR / "CASCADIA-10K-FY2024.txt").write_text(cascadia_txt, encoding="utf-8")

    # Atlas Semiconductor TXT
    atlas_txt = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K
Atlas Semiconductor, Inc. (NASDAQ: ATLS)
For the fiscal year ended December 31, 2024

SYNTHETIC SAMPLE DOCUMENT. Fictional semiconductor company figures invented for testing purposes.

<!-- page: 2 -->
Item 7. Management's Discussion and Analysis

Total revenue was $2,146 million for fiscal year 2024, an increase of 18% compared with $1,824 million in prior-year period.
Gross margin was 51.8%, compared with 49.2% in the prior-year period.
Operating income was $386 million, compared with $291 million in 2023.
Net income was $302 million, compared with $231 million in 2023.

<!-- page: 3 -->
Segment Results:
- Industrial Chips: $1,342 million revenue, $267 million operating income
- Automotive Systems: $524 million revenue, $79 million operating income
- Edge Computing: $280 million revenue, $40 million operating income

<!-- page: 4 -->
Consolidated Balance Sheets (in thousands):
- Total current assets: $741,600
- Total assets: $2,684,500
- Total current liabilities: $402,700
- Total liabilities: $918,400
- Total stockholders' equity: $1,766,100

Cash Flows:
Net cash provided by operating activities was $463 million, compared with $352 million in prior-year period.
"""
    (TXT_DIR / "01_Atlas_Semiconductor_Inc.txt").write_text(atlas_txt, encoding="utf-8")

    # Northstar Cloud Services TXT
    northstar_txt = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM 10-K - ANNUAL REPORT
Northstar Cloud Services, Inc. (NASDAQ: NSTR)
Fiscal year ended December 31, 2024

Item 7. Management's Discussion and Analysis
Northstar Cloud Services reported total annual revenue of $3,450 million in FY2024, representing 24% year-over-year revenue growth compared to $2,780 million in FY2023.

Financial Highlights:
- Annual Recurring Revenue (ARR): $3,120 million, up 27% year over year.
- Gross Margin: 68.4%, compared to 65.2% in FY2023.
- Operating Income: $610 million, up from $415 million in FY2023.
- Net Income: $485 million, compared to $330 million in FY2023.

Consolidated Statements of Financial Position:
- Total current assets: $1,250,000 thousand
- Total assets: $4,120,000 thousand
- Total liabilities: $1,430,000 thousand
- Total stockholders' equity: $2,690,000 thousand

Cash flows from operating activities totaled $820 million for the year.
"""
    (TXT_DIR / "02_Northstar_Cloud_Services_Inc.txt").write_text(northstar_txt, encoding="utf-8")


# --------------------------------------------------------------------------
# 3. CSV Documents
# --------------------------------------------------------------------------

def create_csv_files():
    # Cascadia Statements CSV
    cascadia_rows = [
        ["Company", "Cascadia Robotics, Inc."],
        ["Ticker", "CSCD"],
        ["Filing Type", "Form 10-K Annual Report"],
        ["Fiscal Year", "2024"],
        [],
        ["Segment", "FY2024 Revenue ($M)", "FY2023 Revenue ($M)", "FY2024 Operating Income ($M)"],
        ["Industrial Automation", "1203", "967", "268"],
        ["Consumer Robotics", "421", "398", "31"],
        ["Field Services", "218", "196", "13"],
        ["Total Consolidated", "1842", "1561", "312"],
        [],
        ["Financial Statement Metric", "FY2024 ($M)", "FY2023 ($M)", "Change (%)"],
        ["Total Revenue", "1842", "1561", "18.0%"],
        ["Gross Profit", "998", "805", "24.0%"],
        ["Operating Income", "312", "224", "39.3%"],
        ["Net Income", "241", "173", "39.3%"],
        ["Operating Cash Flows", "389", "298", "30.5%"],
        [],
        ["Balance Sheet Item (in thousands)", "December 31, 2024", "December 31, 2023"],
        ["Total current assets", "612400", "498150"],
        ["Total assets", "2341800", "2014500"],
        ["Total current liabilities", "341200", "298400"],
        ["Total liabilities", "891200", "898400"],
        ["Total stockholders' equity", "1450600", "1116100"],
    ]
    with open(CSV_DIR / "CASCADIA_FY2024_Financial_Statements.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(cascadia_rows)

    # Atlas Semiconductor Segment CSV
    atlas_rows = [
        ["Company", "Atlas Semiconductor, Inc."],
        ["Ticker", "ATLS"],
        ["Fiscal Year", "2024"],
        ["Filing", "10-K SEC Annual Report"],
        [],
        ["Segment", "Period Revenue ($M)", "Prior-Year Revenue ($M)", "Operating Income ($M)"],
        ["Industrial Chips", "1342", "1098", "267"],
        ["Automotive Systems", "524", "472", "79"],
        ["Edge Computing", "280", "254", "40"],
        ["Consolidated Total", "2146", "1824", "386"],
        [],
        ["Balance Sheet Item ($ in thousands)", "Dec 31, 2024", "Dec 31, 2023"],
        ["Total current assets", "741600", "622400"],
        ["Total assets", "2684500", "2311800"],
        ["Total liabilities", "918400", "812700"],
        ["Total stockholders' equity", "1766100", "1499100"],
    ]
    with open(CSV_DIR / "ATLAS_FY2024_Financial_Report.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(atlas_rows)

    # Meridian 10-Q CSV
    meridian_rows = [
        ["Company", "Meridian Energy Storage Technologies, Inc."],
        ["Ticker", "MEST"],
        ["Filing Type", "Form 10-Q Quarterly Report"],
        ["Period Ended", "June 30, 2024 (Q2 FY2024)"],
        [],
        ["Segment", "Q2 FY2024 Revenue ($M)", "Q2 FY2023 Revenue ($M)", "Operating Income ($M)"],
        ["Grid-Scale Storage", "387", "294", "74"],
        ["Commercial & Industrial", "148", "126", "21"],
        ["Software & Services", "52", "41", "14"],
        ["Total Revenues", "587", "461", "109"],
    ]
    with open(CSV_DIR / "MERIDIAN_Q2_FY2024_Financial_Metrics.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(meridian_rows)


# --------------------------------------------------------------------------
# 4. JSON Documents
# --------------------------------------------------------------------------

def create_json_files():
    cascadia_doc = {
        "doc_id": "CASCADIA-10K-FY2024",
        "company": "Cascadia Robotics, Inc.",
        "ticker": "CSCD",
        "doc_type": "10-K",
        "fiscal_year": 2024,
        "filing_date": "2025-02-14",
        "governing_rules": "U.S. GAAP and SEC EDGAR regulations",
        "management_discussion": {
            "total_revenue_millions": 1842,
            "prior_year_revenue_millions": 1561,
            "revenue_growth_pct": 18.0,
            "gross_margin_pct": 54.2,
            "operating_income_millions": 312,
            "net_income_millions": 241,
            "diluted_eps": 1.87
        },
        "segment_results": [
            {"segment": "Industrial Automation", "revenue_fy24": 1203, "revenue_fy23": 967, "operating_income": 268},
            {"segment": "Consumer Robotics", "revenue_fy24": 421, "revenue_fy23": 398, "operating_income": 31},
            {"segment": "Field Services", "revenue_fy24": 218, "revenue_fy23": 196, "operating_income": 13}
        ],
        "consolidated_balance_sheet": {
            "currency": "USD",
            "units": "thousands",
            "period_ended": "2024-12-31",
            "total_current_assets": 612400,
            "total_assets": 2341800,
            "total_current_liabilities": 341200,
            "total_liabilities": 891200,
            "total_stockholders_equity": 1450600
        },
        "cash_flows": {
            "operating_cash_flow_millions": 389,
            "capital_expenditures_millions": 142,
            "free_cash_flow_millions": 247
        }
    }
    with open(JSON_DIR / "CASCADIA-10K-FY2024.json", "w", encoding="utf-8") as f:
        json.dump(cascadia_doc, f, indent=2)

    atlas_doc = {
        "doc_id": "01_Atlas_Semiconductor_Inc",
        "company": "Atlas Semiconductor, Inc.",
        "ticker": "ATLS",
        "doc_type": "10-K",
        "fiscal_year": 2024,
        "management_discussion": {
            "total_revenue_millions": 2146,
            "prior_year_revenue_millions": 1824,
            "gross_margin_pct": 51.8,
            "operating_income_millions": 386,
            "net_income_millions": 302
        },
        "segments": [
            {"name": "Industrial Chips", "revenue": 1342, "prior_revenue": 1098, "operating_income": 267},
            {"name": "Automotive Systems", "revenue": 524, "prior_revenue": 472, "operating_income": 79},
            {"name": "Edge Computing", "revenue": 280, "prior_revenue": 254, "operating_income": 40}
        ],
        "balance_sheet_thousands": {
            "total_current_assets": 741600,
            "total_assets": 2684500,
            "total_current_liabilities": 402700,
            "total_liabilities": 918400,
            "total_stockholders_equity": 1766100
        }
    }
    with open(JSON_DIR / "01_Atlas_Semiconductor_Inc.json", "w", encoding="utf-8") as f:
        json.dump(atlas_doc, f, indent=2)


if __name__ == "__main__":
    print("Generating XLSX files...")
    create_cascadia_xlsx()
    create_atlas_xlsx()
    create_meridian_xlsx()

    print("Generating TXT files...")
    create_txt_files()

    print("Generating CSV files...")
    create_csv_files()

    print("Generating JSON files...")
    create_json_files()

    print("All sample file formats generated successfully!")
