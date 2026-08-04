#!/usr/bin/env python3
"""
Employer Settings DocType Registration Audit Script
Run with: bench --site development.localhost run-script /tmp/audit_settings.py
Or: cd /workspace/development/frappe-bench && env/bin/python /tmp/audit_settings.py
"""
import sys
import os

# Add bench apps to path
bench_path = "/workspace/development/frappe-bench"
sys.path.insert(0, os.path.join(bench_path, "apps", "frappe"))
sys.path.insert(0, os.path.join(bench_path, "apps", "erpnext"))
sys.path.insert(0, os.path.join(bench_path, "apps", "recruitrain_employer"))

import frappe

frappe.init(site="development.localhost", sites_path=os.path.join(bench_path, "sites"))
frappe.connect()

print("=== EMPLOYER SETTINGS DOCTYPE REGISTRATION AUDIT ===\n")

# 1. Check tabDocType
try:
    exists = frappe.db.exists("DocType", "Employer Settings")
    print(f"[1] frappe.db.exists('DocType','Employer Settings') = {repr(exists)}")
except Exception as e:
    print(f"[1] ERROR: {e}")

# 2. Raw SQL check — tabDocType
try:
    raw = frappe.db.sql("SELECT name, module, modified FROM `tabDocType` WHERE name='Employer Settings'", as_dict=True)
    print(f"[2] tabDocType raw: {raw}")
except Exception as e:
    print(f"[2] tabDocType query ERROR: {e}")

# 3. Check tabEmployer Settings exists in MariaDB
try:
    tbl = frappe.db.sql("SHOW TABLES LIKE 'tabEmployer Settings'")
    print(f"[3] tabEmployer Settings table in DB: {repr(tbl)}")
except Exception as e:
    print(f"[3] Table check ERROR: {e}")

# 4. Check new Company columns
try:
    tz_col = frappe.db.sql("SHOW COLUMNS FROM `tabCompany` LIKE 'timezone'")
    lang_col = frappe.db.sql("SHOW COLUMNS FROM `tabCompany` LIKE 'language'")
    theme_col = frappe.db.sql("SHOW COLUMNS FROM `tabCompany` LIKE 'theme'")
    currency_col = frappe.db.sql("SHOW COLUMNS FROM `tabCompany` LIKE 'currency'")
    print(f"[4] tabCompany.timezone  : {repr(tz_col)}")
    print(f"[4] tabCompany.language  : {repr(lang_col)}")
    print(f"[4] tabCompany.theme     : {repr(theme_col)}")
    print(f"[4] tabCompany.currency  : {repr(currency_col)}")
except Exception as e:
    print(f"[4] Company columns ERROR: {e}")

# 5. Installed apps on site
try:
    installed = frappe.get_installed_apps()
    print(f"[5] Installed apps on site: {installed}")
except Exception as e:
    print(f"[5] get_installed_apps ERROR: {e}")

# 6. get_meta
try:
    meta = frappe.get_meta("Employer Settings")
    print(f"[6] get_meta OK — fields: {[f.fieldname for f in meta.fields[:5]]}")
except Exception as e:
    print(f"[6] get_meta ERROR: {e}")

# 7. new_doc
try:
    doc = frappe.new_doc("Employer Settings")
    print(f"[7] new_doc OK — doctype={doc.doctype}, name={doc.name}")
except Exception as e:
    print(f"[7] new_doc ERROR: {e}")

# 8. Check if app is listed in site's apps.txt
try:
    apps_txt = os.path.join(bench_path, "sites", "apps.txt")
    if os.path.exists(apps_txt):
        with open(apps_txt) as f:
            site_apps = f.read()
        print(f"[8] sites/apps.txt: {site_apps.strip()}")
    else:
        site_apps_path = os.path.join(bench_path, "sites", "development.localhost", "apps.txt")
        if os.path.exists(site_apps_path):
            with open(site_apps_path) as f:
                site_apps = f.read()
            print(f"[8] site apps.txt: {site_apps.strip()}")
        else:
            print("[8] apps.txt not found at expected path")
except Exception as e:
    print(f"[8] apps.txt check ERROR: {e}")

# 9. Check site's installed_apps in DB
try:
    installed_db = frappe.db.sql("SELECT app FROM `tabInstalled Application`", as_dict=True)
    print(f"[9] tabInstalled Application: {[r['app'] for r in installed_db]}")
except Exception as e:
    print(f"[9] tabInstalled Application ERROR: {e}")

frappe.destroy()
print("\n=== END AUDIT ===")
