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
                scan_date = ts.date()
                day_start = datetime.combine(scan_date, datetime.min.time())
                day_end = datetime.combine(scan_date, datetime.max.time())
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

                day_start_tz = day_start - timedelta(hours=TIME_OFFSET_HOURS)
                day_end_tz = day_end - timedelta(hours=TIME_OFFSET_HOURS)

                last_log_today = frappe.get_all(
                    "Employee Checkin",
                    filters={
                        "employee": employee,
                        "time": ["between", [day_start_tz, day_end_tz]]
                    },
                    fields=["log_type"],
                    order_by="time desc",
                    limit_page_length=1
                )

                if last_log_today:
                    log_type = "OUT" if last_log_today[0].log_type == "IN" else "IN"
                else:
                    log_type = "IN"                 

                frappe.get_doc({
                    "doctype":  "Employee Checkin",
                    "employee": employee,
                    "time":     ts,
                    "log_type": log_type
                }).insert(ignore_permissions=True)

    return Response("OK", mimetype="text/plain")