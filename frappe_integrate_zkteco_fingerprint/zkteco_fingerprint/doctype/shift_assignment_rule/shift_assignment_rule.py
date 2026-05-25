# Copyright (c) 2026, rayanaouf1512@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, timedelta


class ShiftAssignmentRule(Document):

    def validate(self):
        self._validate_rule_fields()

    def _validate_rule_fields(self):
        if self.rule_type == "Weekly Rotation":
            if not self.weekly_shifts:
                frappe.throw("Weekly Rotation : ajoutez au moins une ligne dans Créneaux hebdomadaires.")

            for row in self.weekly_shifts:
                self._validate_day_format(row.days, f"Ligne {row.idx} – Jours")
                if not row.shift_type:
                    frappe.throw(f"Ligne {row.idx} : Shift Type est obligatoire.")

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
                    f"Utilisez des chiffres de 0 à 6 séparés par des virgules."
                )


# ----------------------------
# Helpers
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
            "employee": employee,
            "shift_type": shift_type,
            "start_date": target_date,
            "docstatus": ["!=", 2],
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
            "doctype": "Shift Assignment",
            "employee": employee,
            "shift_type": shift_type,
            "start_date": target_date,
            "end_date": target_date,
            "status": "Active",
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
# Weekly processor (NEW)
# ----------------------------

def _process_weekly_rotation(rule, target, summary):
    weekday = target.weekday()
    matched = False

    for row in rule.weekly_shifts:
        days = _parse_days(row.days)

        if weekday in days:
            if not row.shift_type:
                frappe.log_error(
                    title="Shift Auto Assign – Champ manquant",
                    message=f"Règle {rule.name} : shift_type manquant ligne {row.idx}",
                )
                summary["errors"] += 1
                return

            _create_shift(rule.employee, row.shift_type, target, summary)
            matched = True
            break

    if not matched:
        summary["skipped"] += 1


def _process_monthly_half(rule, target, summary):
    shift_type = rule.first_half_shift if target.day <= 15 else rule.second_half_shift
    _create_shift(rule.employee, shift_type, target, summary)


def _process_fixed_shift(rule, target, summary):
    _create_shift(rule.employee, rule.shift_type, target, summary)


RULE_PROCESSORS = {
    "Weekly Rotation": _process_weekly_rotation,
    "Monthly Half": _process_monthly_half,
    "Fixed Shift": _process_fixed_shift,
}


# ----------------------------
# Scheduled job
# ----------------------------

def create_tomorrow_shifts():
    target = date.today() + timedelta(days=1)
    summary = {"created": 0, "skipped": 0, "errors": 0}

    # On récupère seulement le "name" — weekly_shifts est une table enfant,
    # pas une colonne SQL, donc on ne peut pas la mettre dans fields.
    rule_names = frappe.get_all(
        "Shift Assignment Rule",
        filters={"is_active": 1},
        fields=["name"]
    )

    if not rule_names:
        return summary

    for r in rule_names:
        # frappe.get_doc charge le document complet avec toutes ses tables enfants
        rule = frappe.get_doc("Shift Assignment Rule", r.name)

        processor = RULE_PROCESSORS.get(rule.rule_type)
        if not processor:
            summary["errors"] += 1
            continue

        try:
            processor(rule, target, summary)
        except Exception as e:
            summary["errors"] += 1
            frappe.log_error(
                title="Shift Auto Assign – Erreur inattendue",
                message=f"{rule.name} : {e}",
            )

    frappe.db.commit()
    return summary