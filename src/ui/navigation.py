"""Single source of truth for the application's pages (used by app.py and the sidebar).

Each entry: (key, script path, title, Material icon, url_path). ``url_path`` "" = default page.
Material Symbols (outlined) are the closest built-in match to Lucide-style line icons.
"""
from __future__ import annotations

NAV: list[tuple[str, str, str, str, str]] = [
    ("overview", "pages/01_Financial_Overview.py", "Financial Overview", ":material/space_dashboard:", ""),
    ("budget", "pages/02_Budget_Expenditure.py", "Budget & Expenditure", ":material/account_balance_wallet:", "budget"),
    ("transactions", "pages/03_Transaction_Register.py", "Transaction Register", ":material/receipt_long:", "transactions"),
    ("forecasting", "pages/04_Forecasting.py", "Forecasting", ":material/query_stats:", "forecasting"),
    ("upload", "pages/05_Data_Upload.py", "Data Upload", ":material/upload_file:", "upload"),
    ("reporting", "pages/06_Reporting.py", "Reporting", ":material/description:", "reporting"),
]
