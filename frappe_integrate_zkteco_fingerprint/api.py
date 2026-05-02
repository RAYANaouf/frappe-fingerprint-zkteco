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
    # Return plain text directly
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
        # Configurable time offset (hours)
        TIME_OFFSET_HOURS = 7  # adjust as needed
        lines = data.split("\n")

        for line in lines:

            fields = line.strip().split()

            if len(fields) >= 3:

                user_id = fields[0]
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
                    "doctype": "Employee Checkin",
                    "employee": employee,
                    "time": ts,
                    "log_type": log_type
                }).insert(ignore_permissions=True)

    return Response("OK", mimetype="text/plain")



def auto_checkout_midnight():
   
    from datetime import datetime, timedelta, time as dt_time
 
    yesterday     = (datetime.now() - timedelta(days=1)).date()
    day_start     = datetime.combine(yesterday, dt_time(0, 0, 0))    # 00:00:00
    day_end       = datetime.combine(yesterday, dt_time(23, 59, 59)) # 23:59:59
    auto_out_time = datetime.combine(yesterday, dt_time(23, 59, 0))  # 23:59:00
 
    frappe.logger().info(f"[MidnightCheckout] Traitement journée {yesterday}")
 
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
        frappe.logger().info(f"[MidnightCheckout] Aucun IN ouvert pour {yesterday}")
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
