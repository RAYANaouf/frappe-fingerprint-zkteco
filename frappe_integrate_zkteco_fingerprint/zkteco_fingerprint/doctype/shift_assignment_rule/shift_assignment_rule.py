# Copyright (c) 2026, rayanaouf1512@gmail.com and contributors
# For license information, please see license.txt

# import frappe
import frappe
from frappe.model.document import Document
from datetime import date, timedelta


class ShiftAssignmentRule(Document):

    def validate(self):
        self._validate_rule_fields()

    def _validate_rule_fields(self):
        if self.rule_type == "Weekly Rotation":
            if not self.morning_days and not self.evening_days:
                frappe.throw("Weekly Rotation : vous devez renseigner au moins Morning Days ou Evening Days.")
            self._validate_day_format(self.morning_days, "Morning Days")
            self._validate_day_format(self.evening_days, "Evening Days")

        elif self.rule_type == "Monthly Half":
            if not self.first_half_shift:
                frappe.throw("Monthly Half : First Half Shift est obligatoire.")
            if not self.second_half_shift:
                frappe.throw("Monthly Half : Second Half Shift est obligatoire.")

        elif self.rule_type == "Fixed Shift":
            if not self.shift_type:
                frappe.throw("Fixed Shift : Shift Type est obligatoire.")

    def _validate_day_format(self, value, label):
        if not value:
            return
        for d in value.split(","):
            d = d.strip()
            if not d.isdigit() or int(d) not in range(7):
                frappe.throw(
                    f"{label} : valeur invalide '{d}'. "
                    f"Utilisez des chiffres de 0 (Lundi) à 6 (Dimanche), séparés par des virgules."
                )


# ----------------------------
# Helpers internes
# ----------------------------

def _parse_days(raw):
    if not raw:
        return []
    return [int(d.strip()) for d in raw.split(",") if d.strip().isdigit()]


def _is_holiday(employee, target_date):
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if not holiday_list:
        return False
    return bool(
        frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": target_date})
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


# ----------------------------
# Processors par rule_type
# ----------------------------

def _process_weekly_rotation(rule, target, summary):
    morning_days = _parse_days(rule.morning_days)
    evening_days = _parse_days(rule.evening_days)
    weekday = target.weekday()

    if weekday in morning_days:
        if not rule.morning_shift_type:
            frappe.log_error(
                title="Shift Auto Assign – Champ manquant",
                message=f"Règle {rule.name} : morning_shift_type non renseigné.",
            )
            summary["errors"] += 1
            return
        _create_shift(rule.employee, rule.morning_shift_type, target, summary)
    elif weekday in evening_days:
        if not rule.evening_shift_type:
            frappe.log_error(
                title="Shift Auto Assign – Champ manquant",
                message=f"Règle {rule.name} : evening_shift_type non renseigné.",
            )
            summary["errors"] += 1
            return
        _create_shift(rule.employee, rule.evening_shift_type, target, summary)
    else:
        summary["skipped"] += 1


def _process_monthly_half(rule, target, summary):
    shift_type = rule.first_half_shift if target.day <= 15 else rule.second_half_shift
    _create_shift(rule.employee, shift_type, target, summary)


def _process_fixed_shift(rule, target, summary):
    _create_shift(rule.employee, rule.shift_type, target, summary)


RULE_PROCESSORS = {
    "Weekly Rotation": _process_weekly_rotation,
    "Monthly Half":    _process_monthly_half,
    "Fixed Shift":     _process_fixed_shift,
}


# ----------------------------
# Scheduled job — appelé par hooks.py
# ----------------------------

def create_tomorrow_shifts():
    target = date.today() + timedelta(days=1)
    summary = {"created": 0, "skipped": 0, "errors": 0}

    rules = frappe.get_all(
        "Shift Assignment Rule",
        filters={"is_active": 1},
        fields=[
            "name", "employee", "rule_type",
            "morning_days", "morning_shift_type",
            "evening_days", "evening_shift_type",
            "first_half_shift", "second_half_shift",
            "shift_type",
        ]
    )

    if not rules:
        frappe.logger().info("[ShiftAssign] Aucune règle active trouvée.")
        return summary

    for rule in rules:
        processor = RULE_PROCESSORS.get(rule.rule_type)
        if not processor:
            frappe.log_error(
                title="Shift Auto Assign – Type inconnu",
                message=f"rule_type '{rule.rule_type}' non géré (règle: {rule.name})",
            )
            summary["errors"] += 1
            continue
        try:
            processor(rule, target, summary)
        except Exception as e:
            summary["errors"] += 1
            frappe.log_error(
                title="Shift Auto Assign – Erreur inattendue",
                message=f"Règle {rule.name} ({rule.employee}) : {e}",
            )

    frappe.db.commit()
    frappe.logger().info(
        f"[ShiftAssign] {target} — {summary['created']} créé(s), "
        f"{summary['skipped']} ignoré(s), {summary['errors']} erreur(s)."
    )
    return summary