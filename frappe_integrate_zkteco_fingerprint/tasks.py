def run_create_tomorrow_shifts():
    from frappe_integrate_zkteco_fingerprint.zkteco_fingerprint.doctype.shift_assignment_rule.shift_assignment_rule import create_tomorrow_shifts
    create_tomorrow_shifts()


def run_daily_attendance_report():
    from frappe_integrate_zkteco_fingerprint.zkteco_fingerprint.doctype.daily_attendance_report.daily_attendance_report import create_daily_attendance_report
    create_daily_attendance_report()


def run_auto_checkout():
    from frappe_integrate_zkteco_fingerprint.auto_checkout_midnight import auto_checkout_midnight
    auto_checkout_midnight()