# Copyright (c) 2026, rayanaouf1512@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, datetime, timedelta


class DailyAttendanceReport(Document):
    pass


LATE_TOLERANCE = 5
EARLY_TOLERANCE = 5

STATUS_PRESENT = "Present"
STATUS_ABSENT = "Absent"
STATUS_LATE = "Late"
STATUS_EARLY = "Early Departure"
STATUS_CHECKIN_NO_CHECKOUT = "Checkin Without Checkout"
STATUS_CHECKOUT_NO_CHECKIN = "Checkout Without Checkin"
STATUS_NO_SHIFT_CHECKIN = "No Shift - Checkin"
STATUS_NO_SHIFT_EARLY_OUT = "No Shift - Early Checkout"
STATUS_UNKNOWN = "Unknown Anomaly"


def _get_shift(employee, d):
    rows = frappe.db.sql("""
        SELECT sa.shift_type,
               st.start_time,
               st.end_time
        FROM   `tabShift Assignment` sa
        JOIN   `tabShift Type`       st ON st.name = sa.shift_type
        WHERE  sa.employee   = %s
          AND  sa.start_date <= %s
          AND  (sa.end_date IS NULL OR sa.end_date >= %s)
          AND  sa.status    = 'Active'
          AND  sa.docstatus = 1
        ORDER  BY sa.start_date DESC
        LIMIT  1
    """, (employee, d, d), as_dict=True)
    return rows[0] if rows else None


def _get_checkins(employee, d):
    start = datetime.combine(d, datetime.min.time())
    end = datetime.combine(d, datetime.max.time())
    return frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee,
            "time": ["between", [start, end]],
            "docstatus": ["!=", 2],
        },
        fields=["time", "log_type"],
        order_by="time asc",
    )


def _is_holiday(employee, d):
    hl = frappe.db.get_value("Employee", employee, "holiday_list")
    if not hl:
        return False
    return bool(frappe.db.exists("Holiday", {"parent": hl, "holiday_date": d}))


def _td_to_dt(d, t):
    if t is None:
        return None
    return datetime.combine(d, (datetime.min + t).time())


def _diff_min(dt1, dt2):
    return int((dt1 - dt2).total_seconds() / 60)


def _analyse(employee, d):
    checkins = _get_checkins(employee, d)
    ins = [c for c in checkins if c.log_type == "IN"]
    outs = [c for c in checkins if c.log_type == "OUT"]

    first_in = ins[0] if ins else None
    last_out = outs[-1] if outs else None

    shift = _get_shift(employee, d)

    row = {
        "employee": employee,
        "shift_type": shift.shift_type if shift else None,
        "scheduled_start": None,
        "scheduled_end": None,
        "checkin_time": first_in.time if first_in else None,
        "checkout_time": last_out.time if last_out else None,
        "worked_hours": 0.0,
        "late_minutes": 0,
        "early_minutes": 0,
        "status": STATUS_UNKNOWN,
        "remarks": "",
    }

    if first_in and last_out:
        row["worked_hours"] = round(
            (last_out.time - first_in.time).total_seconds() / 3600, 2
        )

    if shift:
        s_start = _td_to_dt(d, shift.start_time)
        s_end = _td_to_dt(d, shift.end_time)

        if s_end and s_start and s_end < s_start:
            s_end += timedelta(days=1)

        if s_start:
            row["scheduled_start"] = s_start.strftime("%H:%M:%S")
        if s_end:
            row["scheduled_end"] = s_end.strftime("%H:%M:%S")

        if not first_in and not last_out:
            row["status"] = STATUS_ABSENT
            row["remarks"] = "No checkin or checkout logs recorded."

        elif first_in and not last_out:
            late = _diff_min(first_in.time, s_start)
            row["status"] = STATUS_CHECKIN_NO_CHECKOUT
            if late > LATE_TOLERANCE:
                row["late_minutes"] = late
                row["remarks"] = f"Arrived late by {late} min. Missing checkout log."
            else:
                row["remarks"] = "Arrived on time. Missing checkout log."

        elif not first_in and last_out:
            row["status"] = STATUS_CHECKOUT_NO_CHECKIN
            row["remarks"] = "Checkout log recorded without a corresponding checkin."

        else:
            late = _diff_min(first_in.time, s_start)
            early = _diff_min(s_end, last_out.time) if s_end else 0

            is_late = late > LATE_TOLERANCE
            is_early = early > EARLY_TOLERANCE

            if is_late and is_early:
                row["late_minutes"] = late
                row["early_minutes"] = early
                row["status"] = STATUS_LATE
                row["remarks"] = f"Arrived {late} min late. Left {early} min before shift ended."
            elif is_late:
                row["late_minutes"] = late
                row["status"] = STATUS_LATE
                row["remarks"] = f"Arrived late by {late} min."
            elif is_early:
                row["early_minutes"] = early
                row["status"] = STATUS_EARLY
                row["remarks"] = f"Left {early} min before shift ended."
            else:
                row["status"] = STATUS_PRESENT
                row["remarks"] = "Attendance complies with shift schedule."

    else:
        if not first_in and not last_out:
            return None

        elif first_in:
            row["status"] = STATUS_NO_SHIFT_CHECKIN
            if last_out:
                row["remarks"] = f"Full logs recorded ({row['worked_hours']}h) without an active Shift Assignment."
            else:
                row["remarks"] = "Checkin without checkout and without an active Shift Assignment."
        else:
            row["status"] = STATUS_NO_SHIFT_EARLY_OUT
            row["remarks"] = "Checkout without checkin and without an active Shift Assignment."

    return row


def create_daily_attendance_report(target_date=None):
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    frappe.logger().info(f"[DailyAttendanceReport] Starting generation for {target_date}")

    existing = frappe.db.get_value(
        "Daily Attendance Report", {"date": target_date}, "name"
    )
    if existing:
        frappe.delete_doc(
            "Daily Attendance Report", existing,
            ignore_permissions=True, force=True
        )

    employees = frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name"],
    )

    details = []
    total_present = 0
    total_absent = 0
    total_anomalies = 0

    for emp in employees:
        if _is_holiday(emp.name, target_date):
            continue

        row = _analyse(emp.name, target_date)
        if row is None:
            continue

        if row["status"] == STATUS_PRESENT:
            total_present += 1
        elif row["status"] == STATUS_ABSENT:
            total_absent += 1
        else:
            total_anomalies += 1

        details.append(row)

    if not details:
        frappe.logger().info(
            f"[DailyAttendanceReport] No logs found for {target_date}, report not created."
        )
        return None

    report = frappe.new_doc("Daily Attendance Report")
    report.date = target_date
    report.total_employees = len(employees)
    report.total_present = total_present
    report.total_absent = total_absent
    report.total_anomalies = total_anomalies

    for d in details:
        report.append("details", d)

    report.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.logger().info(
        f"[DailyAttendanceReport] {target_date} — "
        f"{len(details)} rows | "
        f"{total_present} present | "
        f"{total_absent} absent | "
        f"{total_anomalies} anomalies"
    )

    return report.name