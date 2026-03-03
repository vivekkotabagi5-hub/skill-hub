import json, os, base64
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_file
)

# Optional QR code support
try:
    import qrcode
    QR_AVAILABLE = True
except Exception:
    QR_AVAILABLE = False

app = Flask(__name__)
app.secret_key = "change_this_secret"  # change for production!

# ---------- File paths ----------
DATA_DIR = os.path.dirname(__file__)
MENU_FILE = os.path.join(DATA_DIR, "menu.json")
CUSTOMERS_FILE = os.path.join(DATA_DIR, "customers.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
FEEDBACK_FILE = os.path.join(DATA_DIR, "feedback.json")

# ---------- Helpers ----------
def ensure_json_file(path, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def now_ist():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Admin login required.", "warning")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ---------- Ensure JSON files exist ----------
ensure_json_file(MENU_FILE, {
    "1": {"name": "Espresso", "price": 60},
    "2": {"name": "Cappuccino", "price": 90},
    "3": {"name": "Veg Sandwich", "price": 120},
    "4": {"name": "Pizza", "price": 79},
    "5": {"name": "Milk Shake", "price": 35},
    "6": {"name": "Coffee", "price": 25},
    "7": {"name": "Burger", "price": 147}
})
ensure_json_file(CUSTOMERS_FILE, {})
ensure_json_file(ORDERS_FILE, {})
ensure_json_file(FEEDBACK_FILE, {})

# ---------- ROUTES ----------
@app.route("/")
def index():
    menu = load_json(MENU_FILE)
    return render_template("index.html", menu=menu, cafe_name="Royal Cafe")

# Customer signup/login/logout
@app.route("/customer/signup", methods=["GET", "POST"])
def customer_signup():
    if request.method == "POST":
        users = load_json(CUSTOMERS_FILE)
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please provide an email.", "warning")
            return redirect(url_for("customer_signup"))
        if email in users:
            flash("Email already registered.", "danger")
            return redirect(url_for("customer_signup"))
        users[email] = {"name": request.form.get("name", ""), "password": request.form.get("password", "")}
        save_json(CUSTOMERS_FILE, users)
        flash("Signup successful! Please login.", "success")
        return redirect(url_for("customer_login"))
    return render_template("customer_signup.html", cafe_name="Royal Cafe")

@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "POST":
        users = load_json(CUSTOMERS_FILE)
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = users.get(email)
        if user and user.get("password") == password:
            session["customer"] = {"email": email, "name": user.get("name")}
            flash("Logged in successfully!", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials.", "danger")
    return render_template("customer_login.html", cafe_name="Royal Cafe")

@app.route("/customer/logout")
def customer_logout():
    session.pop("customer", None)
    flash("Logged out.", "info")
    return redirect(url_for("index"))

# Admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("username") == "admin" and request.form.get("password") == "1234":
            session["admin_logged_in"] = True
            flash("Admin logged in.", "success")
            return redirect(url_for("admin"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html", cafe_name="Royal Cafe")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("index"))

@app.route("/admin")
@admin_required
def admin():
    menu = load_json(MENU_FILE)
    return render_template("admin.html", menu=menu, cafe_name="Royal Cafe")

@app.route("/admin/menu/add", methods=["POST"])
@admin_required
def add_menu_item():
    menu = load_json(MENU_FILE)
    item_id = str(int(datetime.utcnow().timestamp() * 1000))
    try:
        price = float(request.form.get("price", 0) or 0)
    except ValueError:
        price = 0.0
    menu[item_id] = {"name": request.form.get("name", ""), "price": price, "added_at": now_ist()}
    save_json(MENU_FILE, menu)
    flash("Item added!", "success")
    return redirect(url_for("admin"))

@app.route("/admin/menu/delete/<item_id>")
@admin_required
def delete_menu_item(item_id):
    menu = load_json(MENU_FILE)
    if item_id in menu:
        menu.pop(item_id)
        save_json(MENU_FILE, menu)
        flash("Item deleted.", "info")
    return redirect(url_for("admin"))

# Place order
@app.route("/order", methods=["POST"])
def place_order():
    if not session.get("customer"):
        flash("Please login first.", "warning")
        return redirect(url_for("customer_login"))

    menu = load_json(MENU_FILE)
    orders = load_json(ORDERS_FILE)
    order_items = []
    total = 0.0

    for key, val in request.form.items():
        if key.startswith("qty_"):
            item_id = key.split("_", 1)[1]
            try:
                qty = int(val or 0)
            except ValueError:
                qty = 0
            if qty > 0 and item_id in menu:
                item = menu[item_id]
                subtotal = item.get("price", 0) * qty
                order_items.append({"item_id": item_id, "name": item.get("name", ""), "price": item.get("price", 0), "qty": qty, "subtotal": subtotal})
                total += subtotal

    if not order_items:
        flash("No items selected.", "warning")
        return redirect(url_for("index"))

    order_id = str(int(datetime.utcnow().timestamp() * 1000))
    order = {"id": order_id, "customer": session["customer"]["email"], "name": session["customer"]["name"],
             "items": order_items, "total": total, "status": "placed", "payment_status": "pending",
             "created_at": now_ist()}
    orders[order_id] = order
    save_json(ORDERS_FILE, orders)
    flash("Order placed successfully!", "success")
    return redirect(url_for("final_bill", order_id=order_id))

# View orders
@app.route("/orders")
def view_orders():
    orders = load_json(ORDERS_FILE)
    return render_template("orders.html", orders=orders, cafe_name="Royal Cafe")

# Edit / Cancel
@app.route("/order/edit/<order_id>", methods=["GET", "POST"])
def edit_order(order_id):
    orders = load_json(ORDERS_FILE)
    menu = load_json(MENU_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("view_orders"))

    if not session.get("admin_logged_in"):
        if not session.get("customer") or session["customer"]["email"] != order.get("customer"):
            flash("You cannot edit this order.", "danger")
            return redirect(url_for("view_orders"))

    if request.method == "POST":
        new_items = []
        total = 0.0
        for key, val in request.form.items():
            if key.startswith("qty_"):
                item_id = key.split("_", 1)[1]
                try:
                    qty = int(val or 0)
                except ValueError:
                    qty = 0
                if qty > 0 and item_id in menu:
                    item = menu[item_id]
                    subtotal = item.get("price", 0) * qty
                    new_items.append({"name": item.get("name", ""), "price": item.get("price", 0), "qty": qty, "subtotal": subtotal})
                    total += subtotal
        order["items"] = new_items
        order["total"] = total
        order["status"] = "edited"
        order["edited_at"] = now_ist()
        orders[order_id] = order
        save_json(ORDERS_FILE, orders)
        flash("Order updated!", "success")
        return redirect(url_for("final_bill", order_id=order_id))

    return render_template("edit_order.html", order=order, menu=menu, cafe_name="Royal Cafe")

@app.route("/order/cancel/<order_id>")
def cancel_order(order_id):
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = "cancelled"
        orders[order_id]["cancelled_at"] = now_ist()
        save_json(ORDERS_FILE, orders)
        flash("Order cancelled.", "info")
    return redirect(url_for("view_orders"))

# Payment
@app.route("/payment_success/<order_id>", methods=["POST"])
def payment_success(order_id):
    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("view_orders"))
    order["payment_status"] = "paid"
    order["paid_at"] = now_ist()
    # NOTE: Not auto-marking as completed (Option B)
    orders[order_id] = order
    save_json(ORDERS_FILE, orders)
    flash("Payment received!", "success")
    return redirect(url_for("final_bill", order_id=order_id))

# Final bill
@app.route("/final_bill/<order_id>")
def final_bill(order_id):
    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("view_orders"))

    qr_b64 = None
    if QR_AVAILABLE:
        upi_id = "yourupiid@okaxis"
        amount = "{:.2f}".format(float(order.get("total", 0) or 0))
        payment_link = f"upi://pay?pa={upi_id}&pn=Royal%20Cafe&am={amount}&cu=INR"
        qr = qrcode.make(payment_link)
        buf = BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    return render_template("final_bill.html", order=order, qr_code=qr_b64, cafe_name="Royal Cafe")

# Feedback (allow after payment OR completion)
@app.route("/feedback/<order_id>", methods=["GET", "POST"])
def feedback(order_id):
    orders = load_json(ORDERS_FILE)
    feedbacks = load_json(FEEDBACK_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("index"))

    # Allow feedback if payment is done OR order completed
    if order.get("payment_status") != "paid" and order.get("status") != "completed":
        flash("Please complete payment before giving feedback.", "warning")
        return redirect(url_for("final_bill", order_id=order_id))

    if not session.get("customer") or session["customer"]["email"] != order.get("customer"):
        flash("Please login with the customer account that placed this order to give feedback.", "warning")
        return redirect(url_for("customer_login"))

    if request.method == "POST":
        feedback_id = str(int(datetime.utcnow().timestamp() * 1000))
        feedback_data = {"id": feedback_id, "order_id": order_id, "customer": order.get("customer"), "name": order.get("name"),
                         "rating": request.form.get("rating", ""), "comment": request.form.get("comment", ""), "submitted_at": now_ist()}
        feedbacks[feedback_id] = feedback_data
        save_json(FEEDBACK_FILE, feedbacks)
        flash("Thank you for your feedback!", "success")
        return redirect(url_for("index"))

    return render_template("feedback.html", order=order, cafe_name="Royal Cafe")

# Staff dashboard + actions
@app.route("/staff")
def staff_dashboard():
    orders = load_json(ORDERS_FILE)
    active_orders = {oid: o for oid, o in orders.items() if o.get("status") in ["placed", "preparing"]}
    return render_template("staff.html", orders=active_orders, cafe_name="Royal Cafe")

@app.route("/staff/start/<order_id>")
def mark_order_preparing(order_id):
    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for("staff_dashboard"))

    order["status"] = "preparing"
    order["start_time"] = now_ist()
    orders[order_id] = order
    save_json(ORDERS_FILE, orders)
    flash(f"Order #{order_id} marked as 'Preparing'", "info")
    return redirect(url_for("staff_dashboard"))

@app.route("/staff/complete/<order_id>")
def mark_order_complete(order_id):
    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)
    if not order:
        flash("Order not found", "danger")
        return redirect(url_for("staff_dashboard"))

    order["status"] = "completed"
    order["completed_at"] = now_ist()

    try:
        if "start_time" in order:
            fmt = "%Y-%m-%d %H:%M:%S"
            start_dt = datetime.strptime(order["start_time"], fmt)
            end_dt = datetime.strptime(order["completed_at"], fmt)
            order["wait_time"] = str(int((end_dt - start_dt).total_seconds() // 60)) + " mins"
    except Exception:
        order["wait_time"] = "N/A"

    orders[order_id] = order
    save_json(ORDERS_FILE, orders)
    flash(f"Order #{order_id} marked as Completed", "success")
    return redirect(url_for("staff_dashboard"))

# Reports & admin feedback (kept)
@app.route("/report")
@admin_required
def report():
    orders = load_json(ORDERS_FILE)
    total_orders = len(orders)
    total_revenue = sum(float(o.get("total", 0) or 0) for o in orders.values() if o.get("payment_status") == "paid")
    paid_orders = sum(1 for o in orders.values() if o.get("payment_status") == "paid")
    cancelled_orders = sum(1 for o in orders.values() if o.get("status") == "cancelled")
    return render_template("report.html", total_orders=total_orders, total_revenue=total_revenue,
                           paid_orders=paid_orders, cancelled_orders=cancelled_orders, orders=orders, cafe_name="Royal Cafe")

@app.route("/admin/feedbacks")
@admin_required
def admin_feedbacks():
    feedbacks = load_json(FEEDBACK_FILE)
    return render_template("feedback_dashboard.html", feedbacks=feedbacks, cafe_name="Royal Cafe")

@app.route("/admin/feedback/delete/<fid>")
@admin_required
def delete_feedback(fid):
    feedbacks = load_json(FEEDBACK_FILE)
    if fid in feedbacks:
        feedbacks.pop(fid)
        save_json(FEEDBACK_FILE, feedbacks)
        flash("Feedback deleted successfully.", "info")
    return redirect(url_for("admin_feedbacks"))

# API for polling
@app.route("/api/order/<order_id>")
def api_order(order_id):
    orders = load_json(ORDERS_FILE)
    order = orders.get(order_id)
    if not order:
        return jsonify({"error": "not found"}), 404
    return jsonify({"id": order.get("id"), "status": order.get("status"),
                    "payment_status": order.get("payment_status"), "total": order.get("total"),
                    "items": order.get("items"), "start_time": order.get("start_time"),
                    "completed_at": order.get("completed_at"), "wait_time": order.get("wait_time", "")})

@app.route("/api/orders")
def api_orders():
    return jsonify(load_json(ORDERS_FILE))

@app.route("/api/menu")
def api_menu():
    return jsonify(load_json(MENU_FILE))

# ---------- Serve the uploaded screenshot (demo) ----------
# Developer note: using the uploaded file path so you can demo with the image.
# Local path from your session:
DEMO_IMAGE_PATH = "/mnt/data/Screenshot 2025-11-10 203507.png"
@app.route("/demo_image")
def demo_image():
    if os.path.exists(DEMO_IMAGE_PATH):
        return send_file(DEMO_IMAGE_PATH)
    return "Demo image not found on server.", 404

# Run
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
