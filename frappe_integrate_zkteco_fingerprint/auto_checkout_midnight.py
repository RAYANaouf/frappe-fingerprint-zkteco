def auto_checkout_midnight():
    from datetime import datetime, timedelta, time as dt_time

    today         = datetime.now().date()
    day_start     = datetime.combine(today, dt_time(0, 0, 0))
    day_end       = datetime.combine(today, dt_time(23, 59, 59))
    auto_out_time = datetime.combine(today, dt_time(23, 59, 0))

    frappe.logger().info(f"[MidnightCheckout] Traitement journée {today}")

    open_ins = frappe.db.sql("""
        SELECT
            ci.name,
            ci.employee,
            ci.time,
            ci.shift
        FROM `tabEmployee Checkin` ci
        WHERE ci.log_type = 'IN'
          AND ci.time BETWEEN %s AND %s
          AND NOT EXISTS (
              SELECT 1 FROM `tabEmployee Checkin` co
              WHERE co.employee = ci.employee
                AND co.log_type = 'OUT'
                AND co.time > ci.time
                AND co.time <= %s
          )
        ORDER BY ci.employee, ci.time
    """, (day_start, day_end, day_end), as_dict=True)

    if not open_ins:
        frappe.logger().info(f"[MidnightCheckout] Aucun IN ouvert pour {today}")
        return

    closed = 0
    errors = 0

    for record in open_ins:
        if frappe.db.exists("Employee Checkin", {
            "employee": record.employee,
            "time":     auto_out_time,
            "log_type": "OUT"
        }):
            frappe.logger().info(
                f"[MidnightCheckout] OUT 23:59 déjà existant pour {record.employee}, ignoré"
            )
            continue

        try:
            frappe.get_doc({
                "doctype":        "Employee Checkin",
                "employee":       record.employee,
                "time":           auto_out_time,
                "log_type":       "OUT",
                "shift":          record.shift or "",
                "custom_remarks": "Auto-dépointage minuit"
            }).insert(ignore_permissions=True)

            frappe.db.commit()
            closed += 1
            frappe.logger().info(
                f"[MidnightCheckout] OUT créé — {record.employee} (IN @ {record.time})"
            )

        except Exception as e:
            errors += 1
            frappe.log_error(
                f"[MidnightCheckout] Échec {record.employee} @ {auto_out_time} : {e}"
            )

    frappe.logger().info(
        f"[MidnightCheckout] Terminé — {closed} OUT créés, {errors} erreurs"
    )