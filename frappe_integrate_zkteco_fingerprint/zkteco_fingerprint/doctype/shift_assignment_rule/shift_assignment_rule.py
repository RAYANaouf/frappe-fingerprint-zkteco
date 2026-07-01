import frappe
from frappe.model.document import Document
from datetime import date, timedelta


class ShiftAssignmentRule(Document):

    def validate(self):
        self._validate_rule_fields()

    def _validate_rule_fields(self):
        if self.rule_type == "Weekly Rotation":
            if not self.weekly_shifts:
                frappe.throw("Weekly Rotation: Add at least one row in Weekly Shifts.")

            for row in self.weekly_shifts:
                if not row.days:
                    frappe.throw(f"Row {row.idx}: Day is required.")
                if not row.shift_type:
                    frappe.throw(f"Row {row.idx}: Shift Type is required.")

        elif self.rule_type == "Monthly Half":
            if not self.first_half_shift:
                frappe.throw("Monthly Half: First Half Shift is required.")
            if not self.second_half_shift:
                frappe.throw("Monthly Half: Second Half Shift is required.")

        elif self.rule_type == "Fixed Shift":
            if not self.shift_type:
                frappe.throw("Fixed Shift: Shift Type is required.")


def _is_holiday(employee, target_date):
    holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")
    if not holiday_list:
        return False
    return bool(
        frappe.db.exists("Holiday", {"parent": holiday_list, "holiday_date": target_date})
    )


def _create_shift(employee, shift_type, target_date, summary):
    if _is_holiday(employee, target_date):
        summary["skipped"] += 1
        return

    existing_assignment = frappe.db.get_value(
        "Shift Assignment",
        {"employee": employee, "status": "Active", "docstatus": 1},
        ["name", "shift_type"],
        as_dict=True
    )

    if existing_assignment:
        if existing_assignment.shift_type == shift_type:
            summary["skipped"] += 1
            return

        try:
            frappe.db.set_value("Shift Assignment", existing_assignment.name, "shift_type", shift_type)
            summary["created"] += 1
        except Exception as e:
            summary["errors"] += 1
            frappe.log_error(
                title="Shift Auto Assign – Error on Update",
                message=f"Impossible de mettre à jour le shift pour {employee} vers {shift_type} : {e}",
            )
    else:
        try:
            doc = frappe.get_doc({
                "doctype": "Shift Assignment",
                "employee": employee,
                "shift_type": shift_type,
                "start_date": target_date,
                "end_date": None,
                "status": "Active",
            })
            doc.insert(ignore_permissions=True)
            doc.submit()
            summary["created"] += 1
        except Exception as e:
            summary["errors"] += 1
            frappe.log_error(
                title="Shift Auto Assign – Error on Creation",
                message=f"Impossible de créer le premier shift pour {employee} | {shift_type} : {e}",
            )


def _process_weekly_rotation(rule, target, summary):
    weekday = target.weekday()  
    matched = False

    DAYS_MAP = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    for row in rule.weekly_shifts:
        if row.days in DAYS_MAP:
            row_day = DAYS_MAP.index(row.days)
        else:
            continue

        if weekday == row_day:
            if not row.shift_type:
                frappe.log_error(
                    title="Shift Auto Assign – Missing Field",
                    message=f"Rule {rule.name}: Missing shift_type on row {row.idx}",
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


def create_tomorrow_shifts():
    target = date.today() + timedelta(days=1)