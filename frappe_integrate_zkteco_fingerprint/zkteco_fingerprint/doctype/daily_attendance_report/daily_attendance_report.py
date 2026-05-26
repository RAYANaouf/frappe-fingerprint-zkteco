# Copyright (c) 2026, rayanaouf1512@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, datetime, timedelta


class DailyAttendanceReport(Document):
    pass


# ─────────────────────────────────────────
#  Constantes
# ─────────────────────────────────────────

LATE_TOLERANCE  = 5  # minutes
EARLY_TOLERANCE = 5  # minutes

STATUS_PRESENT             = "Present"
STATUS_ABSENT              = "Absent"
STATUS_LATE                = "Retard"
STATUS_EARLY               = "Depart Anticipe"
STATUS_CHECKIN_NO_CHECKOUT = "Checkin Sans Checkout"
STATUS_CHECKOUT_NO_CHECKIN = "Checkout Sans Checkin"
STATUS_NO_SHIFT_CHECKIN    = "Sans Shift - Checkin"
STATUS_NO_SHIFT_EARLY_OUT  = "Sans Shift - Checkout Anticipe"
STATUS_UNKNOWN             = "Anomalie Inconnue"


# ─────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────

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
    end   = datetime.combine(d, datetime.max.time())
    return frappe.get_all(
        "Employee Checkin",
        filters={
            "employee":  employee,
            "time":      ["between", [start, end]],
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
    """timedelta (champ Time Frappe) → datetime"""
    if t is None:
        return None
    return datetime.combine(d, (datetime.min + t).time())


def _diff_min(dt1, dt2):
    return int((dt1 - dt2).total_seconds() / 60)


# ─────────────────────────────────────────
#  Analyse d'un employé
# ─────────────────────────────────────────

def _analyse(employee, d):
    checkins = _get_checkins(employee, d)
    ins  = [c for c in checkins if c.log_type == "IN"]
    outs = [c for c in checkins if c.log_type == "OUT"]

    first_in = ins[0]   if ins  else None
    last_out = outs[-1] if outs else None

    shift = _get_shift(employee, d)

    row = {
        "employee":        employee,
        "shift_type":      shift.shift_type if shift else None,
        "scheduled_start": None,
        "scheduled_end":   None,
        "checkin_time":    first_in.time if first_in else None,
        "checkout_time":   last_out.time if last_out else None,
        "worked_hours":    0.0,
        "late_minutes":    0,
        "early_minutes":   0,
        "status":          STATUS_UNKNOWN,
        "remarks":         "",
    }

    if first_in and last_out:
        row["worked_hours"] = round(
            (last_out.time - first_in.time).total_seconds() / 3600, 2
        )

    # ── Avec shift assigné ──────────────────────────────────────────────────
    if shift:
        s_start = _td_to_dt(d, shift.start_time)
        s_end   = _td_to_dt(d, shift.end_time)

        if s_end and s_start and s_end < s_start:
            s_end += timedelta(days=1)

        if s_start:
            row["scheduled_start"] = s_start.strftime("%H:%M:%S")
        if s_end:
            row["scheduled_end"] = s_end.strftime("%H:%M:%S")

        # CAS — Absent
        if not first_in and not last_out:
            row["status"]  = STATUS_ABSENT
            row["remarks"] = "Aucun pointage enregistré."

        # CAS — Checkin sans checkout
        elif first_in and not last_out:
            late = _diff_min(first_in.time, s_start)
            row["status"] = STATUS_CHECKIN_NO_CHECKOUT
            if late > LATE_TOLERANCE:
                row["late_minutes"] = late
                row["remarks"] = f"Arrivée avec {late} min de retard. Pas de checkout."
            else:
                row["remarks"] = "Arrivée à l'heure. Pas de checkout."

        # CAS — Checkout sans checkin
        elif not first_in and last_out:
            row["status"]  = STATUS_CHECKOUT_NO_CHECKIN
            row["remarks"] = "Checkout enregistré sans checkin correspondant."

        # CAS normal — checkin + checkout présents
        else:
            late  = _diff_min(first_in.time, s_start)
            early = _diff_min(s_end, last_out.time) if s_end else 0

            is_late  = late  > LATE_TOLERANCE
            is_early = early > EARLY_TOLERANCE

            if is_late and is_early:
                row["late_minutes"]  = late
                row["early_minutes"] = early
                row["status"]  = STATUS_LATE
                row["remarks"] = (
                    f"Retard de {late} min à l'arrivée. "
                    f"Départ {early} min avant la fin du shift."
                )
            elif is_late:
                row["late_minutes"] = late
                row["status"]  = STATUS_LATE
                row["remarks"] = f"Arrivée avec {late} min de retard."
            elif is_early:
                row["early_minutes"] = early
                row["status"]  = STATUS_EARLY
                row["remarks"] = f"Départ {early} min avant la fin du shift."
            else:
                row["status"]  = STATUS_PRESENT
                row["remarks"] = "Présence conforme au shift."

    # ── Sans shift assigné ──────────────────────────────────────────────────
    else:
        if not first_in and not last_out:
            return None  # rien à signaler

        elif first_in:
            row["status"] = STATUS_NO_SHIFT_CHECKIN
            if last_out:
                row["remarks"] = (
                    f"Pointage complet ({row['worked_hours']}h) "
                    f"sans Shift Assignment actif."
                )
            else:
                row["remarks"] = "Checkin sans checkout et sans Shift Assignment actif."
        else:
            row["status"]  = STATUS_NO_SHIFT_EARLY_OUT
            row["remarks"] = "Checkout sans checkin et sans Shift Assignment actif."

    return row


# ─────────────────────────────────────────
#  Fonction principale — appelée par hooks.py
# ─────────────────────────────────────────

def create_daily_attendance_report(target_date=None):
    """
    Crée le Daily Attendance Report pour target_date.
    Par défaut : J-1 (hier) pour avoir tous les pointages complets.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    if isinstance(target_date, str):
        target_date = datetime.strptime(target_date, "%Y-%m-%d").date()

    frappe.logger().info(f"[DailyAttendanceReport] Début génération pour {target_date}")

    # Supprimer le rapport existant pour ce jour si déjà généré
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

    details         = []
    total_present   = 0
    total_absent    = 0
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

    # ← ICI correctement — APRÈS la boucle, pas dedans
    if not details:
        frappe.logger().info(
            f"[DailyAttendanceReport] Aucun pointage pour {target_date}, rapport non créé."
        )
        return None

    report = frappe.new_doc("Daily Attendance Report")
    report.date            = target_date
    report.total_employees = len(employees)
    report.total_present   = total_present
    report.total_absent    = total_absent
    report.total_anomalies = total_anomalies

    for d in details:
        report.append("details", d)

    report.insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.logger().info(
        f"[DailyAttendanceReport] {target_date} — "
        f"{len(details)} lignes | "
        f"{total_present} présents | "
        f"{total_absent} absents | "
        f"{total_anomalies} anomalies"
    )

    return report.name