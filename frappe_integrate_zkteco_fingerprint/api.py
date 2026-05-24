import frappe
from werkzeug.wrappers import Response

# ----------------------------
# Core functions
# ----------------------------

@frappe.whitelist(allow_guest=True)
def iclock_getrequest():
    """
    Original function — returns the command for the K50 device.
    """
    frappe.logger().info("iclock_getrequest called")
    frappe.log_error("iclock_getrequest called")
    return Response("DATA QUERY USERINFO\n", mimetype="text/plain")


@frappe.whitelist(allow_guest=True)
def iclock_cdata():
    """
    Original function — handles POSTed attendance logs from K50.
    """
    frappe.log_error("iclock_cdata called")
    data = frappe.request.data.decode("utf-8", errors="ignore").strip()
    frappe.log_error(f"iclock_cdata data: {data}")
    table = frappe.request.args.get("table")
    frappe.log_error(f"iclock_cdata table: {table}")

    if table and table.upper().startswith("ATTLOG"):
        from datetime import datetime, timedelta
        TIME_OFFSET_HOURS = 7
        lines = data.split("\n")

        for line in lines:
            fields = line.strip().split()

            if len(fields) >= 3:
                user_id   = fields[0]
                timestamp = f"{fields[1]} {fields[2]}"

                employee = frappe.db.get_value(
                    "Employee",
                    {"custom_attendance_device_employee_id": user_id},
                    "name"
                )

                if not employee:
                    frappe.log_error(f"No employee mapped for device user {user_id}")
                    continue

                ts = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
                ts = ts - timedelta(hours=TIME_OFFSET_HOURS)

                existing = frappe.db.sql("""
                    SELECT name FROM `tabEmployee Checkin`
                    WHERE employee=%s
                    AND time >= %s
                    ORDER BY time DESC
                    LIMIT 1
                """, (employee, ts - timedelta(seconds=30)))

                if existing:
                    frappe.log_error(f"Duplicate scan ignored for {employee}")
                    continue

                last_log = frappe.get_all(
                    "Employee Checkin",
                    filters={"employee": employee},
                    fields=["log_type"],
                    order_by="time desc",
                    limit_page_length=1
                )

                log_type = "IN"
                if last_log and last_log[0].log_type == "IN":
                    log_type = "OUT"

                frappe.get_doc({
                    "doctype":  "Employee Checkin",
                    "employee": employee,
                    "time":     ts,
                    "log_type": log_type
                }).insert(ignore_permissions=True)

    return Response("OK", mimetype="text/plain")





RULE1_EMPLOYEES = [
    {
        "employee_name": "Oussama Laraba",
        "shifts": {
            "Morning Shift": [3, 0, 1],
            "Evening Shift": [2, 5, 6],
        },
    },
    {
        "employee_name": "Amine Babekar",
        "shifts": {
            "Morning Shift": [2, 5, 6],
            "Evening Shift": [0, 1, 3],
        },
    },
]

RULE2_EMPLOYEES = [
    {
        "employee_name": "Abdelhak Zoubiri",
        "first_half":  "Morning Shift",
        "second_half": "Evening Shift",
        "off_days":[],
    },
    {
        "employee_name": "Redouane Bouzad",
        "first_half":  "Evening Shift",
        "second_half": "Morning Shift",
        "off_days":[],
    },
]

RULE3_EMPLOYEES = [
    {"employee_name": "Selmane Frahi",    "shift": "Evening Shift", "off_days": []},
    {"employee_name": "Hichem Akli",      "shift": "Evening Shift", "off_days": []},
    {"employee_name": "Salem Adel",       "shift": "Morning Shift", "off_days": [3]},
    {"employee_name": "Rayan Aouf",       "shift": "Morning Shift", "off_days": []},
    {"employee_name": "Youcef Kaydi",     "shift": "Morning Shift", "off_days": []},
    {"employee_name": "Amine Ferouane",   "shift": "Morning Shift", "off_days": []},
    {"employee_name": "Farid Neggaz",     "shift": "Morning Shift", "off_days": []},
    {"employee_name": "Mehdi Zitoni",     "shift": "Morning Shift", "off_days": []},
]


def _get_employee_id(employee_name):
    result = frappe.db.get_value(
        "Employee",
        {"employee_name": employee_name, "status": "Active"},
        "name",
    )
    if not result:
        frappe.log_error(
            title="Shift Auto Assign – Employé introuvable",
            message=f"Employé non trouvé : {employee_name}",
        )
    return result


def _is_holiday(employee, target_date):
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if not holiday_list:
        return False
    return bool(
        frappe.db.exists(
            "Holiday",
            {"parent": holiday_list, "holiday_date": target_date},
        )
    )


def _shift_exists(employee, shift_type, target_date):
    return frappe.db.exists(
        "Shift Assignment",
        {
            "employee":   employee,
            "shift_type": shift_type,
            "start_date": target_date,
            "docstatus":  ["!=", 2],
        },
    )


def _create_shift(employee, shift_type, target_date, summary):
    if _is_holiday(employee, target_date):
        summary["skipped"] += 1
        return
    if _shift_exists(employee, shift_type, target_date):
        summary["skipped"] += 1
        return
    try:
        doc = frappe.get_doc({
            "doctype":    "Shift Assignment",
            "employee":   employee,
            "shift_type": shift_type,
            "start_date": target_date,
            "end_date":   target_date,
            "status":     "Active",
        })
        doc.insert(ignore_permissions=True)
        doc.submit()
        summary["created"] += 1
    except Exception as e:
        summary["errors"] += 1
        frappe.log_error(
            title="Shift Auto Assign – Erreur",
            message=f"{employee} | {shift_type} | {target_date} : {e}",
        )


def create_tomorrow_shifts():
    from datetime import date, timedelta

    target = date.today() + timedelta(days=1)
    summary = {"created": 0, "skipped": 0, "errors": 0}

    for config in RULE1_EMPLOYEES:
        employee = _get_employee_id(config["employee_name"])
        if not employee:
            summary["errors"] += 1
            continue
        day_map = {}
        for shift_type, days in config["shifts"].items():
            for d in days:
                day_map[d] = shift_type
        shift_type = day_map.get(target.weekday())
        if shift_type:
            _create_shift(employee, shift_type, target, summary)

    for config in RULE2_EMPLOYEES:
        employee = _get_employee_id(config["employee_name"])
        if not employee:
            summary["errors"] += 1
            continue
        shift_type = config["first_half"] if target.day <= 15 else config["second_half"]
        _create_shift(employee, shift_type, target, summary)

    for config in RULE3_EMPLOYEES:
        employee = _get_employee_id(config["employee_name"])
        if not employee:
            summary["errors"] += 1
            continue
        if target.weekday() not in config["off_days"]:
            _create_shift(employee, config["shift"], target, summary)

    frappe.db.commit()
    frappe.logger().info(
        f"[ShiftAssign] {target} — {summary['created']} créé(s), "
        f"{summary['skipped']} ignoré(s), {summary['errors']} erreur(s)."
    )
    return summary