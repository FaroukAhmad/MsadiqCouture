import re
import hashlib
import hmac
import os
import time
import secrets
from functools import wraps
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from config import Config
from notifications import NotificationService
from payments import PaystackGateway, PaymentGatewayError
import image_storage

app = Flask(__name__, static_folder="public/static", static_url_path="/static")

# Cache-busting for CSS/JS: browsers otherwise keep serving an old cached
# copy of styles.css/app.js after a deploy, even once the server has the
# new file. VERCEL_GIT_COMMIT_SHA changes on every deploy and is the same
# across all serverless instances of that deploy; falls back to process
# start time for local development.
STATIC_VERSION = os.environ.get("VERCEL_GIT_COMMIT_SHA") or str(int(time.time()))


@app.context_processor
def inject_static_version():
    return {"static_version": STATIC_VERSION}
app.config.from_object(Config)
try:
    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
except OSError:  # read-only filesystem: don't crash at import time
    app.logger.warning("Upload folder %s is not writable", app.config["UPLOAD_FOLDER"])

db = SQLAlchemy(app)


class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    users = db.relationship("User", backref="role_ref", lazy=True)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"), nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_admin(self):
        return self.role_ref and self.role_ref.name == "admin"


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    styles = db.relationship("Style", backref="category_ref", lazy=True)


class Style(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(160), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)
    gender = db.Column(db.String(40), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    featured = db.Column(db.Boolean, default=False)
    new_arrival = db.Column(db.Boolean, default=False)
    description = db.Column(db.Text, nullable=False)
    colors = db.Column(db.String(255), nullable=False)
    fabrics = db.Column(db.String(255), nullable=False)
    lead_time = db.Column(db.String(60), nullable=False)
    availability = db.Column(db.String(60), nullable=False)
    image_main = db.Column(db.String(255), nullable=False)
    image_gallery = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Float, default=4.8)
    reviews = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def images(self):
        return self.gallery_images

    @property
    def category(self):
        return self.category_ref.name if self.category_ref else "Uncategorized"

    @property
    def gallery_images(self):
        images = []
        if self.image_gallery:
            images = [item.strip() for item in self.image_gallery.split("|") if item.strip()]
        if not images and self.image_main:
            images = [self.image_main]
        if not images:
            images = ["https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80"]
        return images

    @property
    def colors_list(self):
        return [item.strip() for item in (self.colors or "").split("|") if item.strip()]

    @property
    def fabric_list(self):
        return [item.strip() for item in (self.fabrics or "").split("|") if item.strip()]

    @property
    def fabric(self):
        return self.fabric_list


class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(60), default="Available")
    image = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    customer_name = db.Column(db.String(120), nullable=False)
    service_name = db.Column(db.String(160), nullable=False)
    preferred_date = db.Column(db.String(60), nullable=False)
    preferred_time = db.Column(db.String(60), nullable=False)
    status = db.Column(db.String(40), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    order_number = db.Column(db.String(40), unique=True, nullable=False)
    customer_name = db.Column(db.String(160), nullable=False)
    item_name = db.Column(db.String(160), nullable=False)
    total_amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(60), default="Order Received")
    delivery_status = db.Column(db.String(60), default="Pending")
    admin_response = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), default="NGN")
    status = db.Column(db.String(40), default="Pending")
    gateway = db.Column(db.String(40), default="Paystack")
    transaction_reference = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class UserProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False)
    avatar = db.Column(db.String(255), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    user = db.relationship("User", backref=db.backref("profile", uselist=False, cascade="all, delete-orphan"))


class MeasurementRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    customer_name = db.Column(db.String(160), nullable=False)
    garment_name = db.Column(db.String(160), nullable=False)
    chest = db.Column(db.String(30), nullable=False)
    waist = db.Column(db.String(30), nullable=False)
    hip = db.Column(db.String(30), nullable=False)
    sleeve = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(40), default="Submitted")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


def seed_demo_data():
    with app.app_context():
        db.create_all()
        if db.engine.dialect.name == 'sqlite':
            columns = {column['name'] for column in inspect(db.engine).get_columns('order')}
            if 'admin_response' not in columns:
                db.session.execute(db.text('ALTER TABLE "order" ADD COLUMN admin_response TEXT'))
                db.session.commit()

        if Role.query.count() == 0:
            db.session.add_all([
                Role(name="customer"),
                Role(name="staff"),
                Role(name="admin")
            ])
            db.session.commit()

        if User.query.count() == 0:
            admin_role = Role.query.filter_by(name="admin").first()
            customer_role = Role.query.filter_by(name="customer").first()
            db.session.add_all([
                User(full_name="Msadiq Administrator", email="admin@msadiq.com", phone="08030000000", password_hash=generate_password_hash("admin123"), role_id=admin_role.id),
                User(full_name="Aisha Bello", email="aisha@msadiq.com", phone="08050000001", password_hash=generate_password_hash("customer123"), role_id=customer_role.id),
            ])
            db.session.commit()

        if Category.query.count() == 0:
            db.session.add_all([
                Category(name="Traditional Wear", slug="traditional-wear"),
                Category(name="Corporate Wear", slug="corporate-wear"),
                Category(name="Wedding Wear", slug="wedding-wear"),
                Category(name="Modern Wear", slug="modern-wear"),
            ])
            db.session.commit()

        if Style.query.count() == 0:
            category_map = {category.name: category.id for category in Category.query.all()}
            db.session.add_all([
                Style(
                    name="Royal Kaftan Set",
                    slug="royal-kaftan-set",
                    category_id=category_map["Traditional Wear"],
                    gender="Women",
                    price=185000,
                    featured=True,
                    new_arrival=True,
                    description="Luxury kaftan with premium movement, elegant finishing, and rich African tailoring details.",
                    colors="Gold|Ivory|Deep Maroon",
                    fabrics="Aso-oke|Silk blend|Cotton satin",
                    lead_time="10-14 days",
                    availability="In stock",
                    image_main="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80",
                    image_gallery="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80|https://images.unsplash.com/photo-1496747611176-843222e1e57c?auto=format&fit=crop&w=900&q=80",
                    rating=4.8,
                    reviews=48,
                ),
                Style(
                    name="Executive Senator Suit",
                    slug="executive-senator-suit",
                    category_id=category_map["Corporate Wear"],
                    gender="Men",
                    price=220000,
                    featured=True,
                    new_arrival=False,
                    description="Refined senator suit made for professional confidence, polished lines, and excellent drape.",
                    colors="Charcoal|Navy|Black",
                    fabrics="Italian wool|Premium cotton",
                    lead_time="12-16 days",
                    availability="Made to order",
                    image_main="https://images.unsplash.com/photo-1507679799987-c73779587ccf?auto=format&fit=crop&w=900&q=80",
                    image_gallery="https://images.unsplash.com/photo-1507679799987-c73779587ccf?auto=format&fit=crop&w=900&q=80|https://images.unsplash.com/photo-1521572267360-ee0c2909d518?auto=format&fit=crop&w=900&q=80",
                    rating=4.7,
                    reviews=36,
                ),
                Style(
                    name="Classic Bridal Agbada",
                    slug="classic-bridal-agbada",
                    category_id=category_map["Wedding Wear"],
                    gender="Men",
                    price=310000,
                    featured=False,
                    new_arrival=True,
                    description="A regal bridal agbada with premium tailoring, rich texture, and event-ready elegance.",
                    colors="Gold|White|Forest Green",
                    fabrics="Brocade|Silk blend|Cotton blend",
                    lead_time="14-18 days",
                    availability="Custom fitting",
                    image_main="https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=900&q=80",
                    image_gallery="https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=900&q=80|https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=900&q=80",
                    rating=4.9,
                    reviews=19,
                ),
                Style(
                    name="Signature Jalabiya",
                    slug="signature-jalabiya",
                    category_id=category_map["Modern Wear"],
                    gender="Women",
                    price=170000,
                    featured=True,
                    new_arrival=False,
                    description="Modern silhouette with graceful tailoring and premium comfort for day-to-evening elegance.",
                    colors="Sand|Berry|Cream",
                    fabrics="Crepe|Premium cotton|Chiffon",
                    lead_time="8-12 days",
                    availability="In stock",
                    image_main="https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=900&q=80",
                    image_gallery="https://images.unsplash.com/photo-1529139574466-a303027c1d8b?auto=format&fit=crop&w=900&q=80|https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80",
                    rating=4.8,
                    reviews=43,
                )
            ])
            db.session.commit()

        if Service.query.count() == 0:
            db.session.add_all([
                Service(name="Custom Tailoring", description="Bespoke textile design and fit consultation for unique garments.", price=95000, duration="7-10 days", status="Available", image="https://images.unsplash.com/photo-1521572267360-ee0c2909d518?auto=format&fit=crop&w=900&q=80"),
                Service(name="Wedding Tailoring", description="Luxury bridal and event tailoring with private fitting support.", price=160000, duration="14-21 days", status="Popular", image="https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?auto=format&fit=crop&w=900&q=80"),
                Service(name="Alteration & Repairs", description="Precise fitting adjustments and garment restoration for existing pieces.", price=25000, duration="3-5 days", status="Available", image="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80")
            ])
            db.session.commit()

        if Booking.query.count() == 0:
            db.session.add_all([
                Booking(customer_name="Ada Nwosu", service_name="Custom Tailoring", preferred_date="2026-09-22", preferred_time="10:00 AM", status="Confirmed"),
                Booking(customer_name="Tobi Martins", service_name="Wedding Tailoring", preferred_date="2026-09-24", preferred_time="2:30 PM", status="Pending"),
            ])
            db.session.commit()

        if Order.query.count() == 0:
            db.session.add_all([
                Order(order_number="TAIL-2026-000001", customer_name="Ada Nwosu", item_name="Royal Kaftan Set", total_amount=185000, status="Payment Confirmed", delivery_status="Fabric Confirmed"),
                Order(order_number="TAIL-2026-000002", customer_name="Tobi Martins", item_name="Executive Senator Suit", total_amount=220000, status="Measurement Confirmed", delivery_status="In Production"),
                Order(order_number="TAIL-2026-000003", customer_name="Chinedu Okafor", item_name="Signature Jalabiya", total_amount=170000, status="Order Received", delivery_status="Pending"),
            ])
            db.session.commit()

        if Payment.query.count() == 0:
            db.session.add_all([
                Payment(order_number="TAIL-2026-000001", amount=185000, currency="NGN", status="Successful", gateway="Paystack", transaction_reference="PS-1001"),
                Payment(order_number="TAIL-2026-000002", amount=220000, currency="NGN", status="Pending", gateway="Flutterwave", transaction_reference="FW-1002"),
                Payment(order_number="TAIL-2026-000003", amount=170000, currency="NGN", status="Partially Paid", gateway="Paystack", transaction_reference="PS-1003"),
            ])
            db.session.commit()

        catalog_names = {
            "Royal Kaftan Set": "Babbar Riga Royale",
            "Executive Senator Suit": "Hausa Jampa Executive",
            "Classic Bridal Agbada": "Jampa Wedding Ensemble",
            "Signature Jalabiya": "Babbar Riga Signature",
        }
        catalog_changed = False
        for old_name, new_name in catalog_names.items():
            style = Style.query.filter_by(name=old_name).first()
            if style:
                style.name = new_name
                catalog_changed = True
        for old_name, new_name in catalog_names.items():
            for order in Order.query.filter_by(item_name=old_name).all():
                order.item_name = new_name
                catalog_changed = True
        if catalog_changed:
            db.session.commit()


try:
    with app.app_context():
        db.create_all()
        if db.engine.dialect.name == 'sqlite':
            columns = {column['name'] for column in inspect(db.engine).get_columns('order')}
            if 'admin_response' not in columns:
                db.session.execute(db.text('ALTER TABLE "order" ADD COLUMN admin_response TEXT'))
                db.session.commit()
except Exception as _db_init_err:
    app.logger.error("Database init skipped at startup: %s", _db_init_err)

if app.config["SEED_DEMO_DATA"]:
    try:
        seed_demo_data()
    except Exception as _seed_err:
        app.logger.error("Demo seed skipped: %s", _seed_err)

if app.config["ENVIRONMENT"] == "production" and app.config["SECRET_KEY"] == "dev-only-change-me":
    app.logger.warning(
        "WARNING: SECRET_KEY is using the insecure default. "
        "Set SECRET_KEY in your Vercel Environment Variables."
    )


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if session.get("role") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def verify_csrf():
    expected = session.get("csrf_token")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def allowed_upload(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"jpg", "jpeg", "png", "webp"}


def store_uploaded_image(file_storage, prefix, folder="msadiq"):
    """Save an uploaded image and return its public URL.

    Uses Cloudinary when configured (works on Vercel, since /tmp there is
    ephemeral and not web-served). Falls back to local disk otherwise,
    which is fine for local development but NOT for a Vercel deployment.
    Raises image_storage.UploadError with a user-facing message on failure.
    """
    if image_storage.is_configured():
        return image_storage.upload_image(file_storage, folder=folder)

    if current_app.config.get("ON_VERCEL"):
        raise image_storage.UploadError(
            "Image uploads aren't set up yet on this deployment. "
            "Paste an image URL instead, or ask your developer to configure Cloudinary."
        )

    filename = f"{prefix}-{secrets.token_hex(8)}-{secure_filename(file_storage.filename)}"
    file_storage.save(Path(current_app.config['UPLOAD_FOLDER']) / filename)
    return url_for('static', filename=f'uploads/{filename}')


def notify_customer(customer_name, subject, body):
    user = User.query.filter_by(full_name=customer_name).first()
    if not user:
        return
    service = NotificationService(current_app.config)
    try:
        service.email(user.email, subject, body)
        service.sms(user.phone, body)
    except Exception:
        app.logger.exception("Customer notification failed")


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def enforce_csrf():
    if request.method == "POST" and request.endpoint != "paystack_webhook" and not verify_csrf():
        return jsonify({"error": "invalid csrf token"}), 400


def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("-")


def unique_style_slug(requested, name, exclude_id=None):
    """Slugify `requested` (falling back to `name`), then make it unique.

    An empty/blank slug field previously passed through as "" and caused a
    duplicate-key error on the second style. This always returns a
    non-empty, collision-free slug.
    """
    base = slugify(requested) or slugify(name) or "style"
    slug = base
    n = 2
    query = Style.query.filter(Style.slug == slug)
    if exclude_id is not None:
        query = query.filter(Style.id != exclude_id)
    while query.first() is not None:
        slug = f"{base}-{n}"
        n += 1
        query = Style.query.filter(Style.slug == slug)
        if exclude_id is not None:
            query = query.filter(Style.id != exclude_id)
    return slug


def dashboard_stats():
    total_revenue = sum(order.total_amount for order in Order.query.all())
    active_production = Order.query.filter(~Order.status.in_(["Order Received", "Completed"])).count()
    return {
        "customers": User.query.count(),
        "orders": Order.query.count(),
        "pending_orders": Order.query.filter(Order.status.in_(["Order Received", "Measurement Confirmed"])).count(),
        "production_active": active_production,
        "revenue": f"₦{round(total_revenue / 1000000, 1)}M",
        "appointments": Booking.query.count(),
        "pending_payments": Payment.query.filter(Payment.status == "Pending").count(),
        "completed_orders": Order.query.filter(Order.status == "Completed").count(),
    }


@app.route('/')
def index():
    featured = Style.query.order_by(Style.created_at.desc()).limit(8).all()
    services = Service.query.limit(3).all()
    return render_template('index.html', styles=featured, services=services, stats=dashboard_stats())


@app.route('/healthz')
def healthz():
    try:
        db.session.execute(db.text('SELECT 1'))
        return jsonify({'status': 'ok'}), 200
    except Exception:
        app.logger.exception('Health check failed')
        return jsonify({'status': 'unhealthy'}), 503


@app.route('/styles')
def styles_page():
    query = request.args.get('q', '').strip().lower()
    category = request.args.get('category', 'All')
    selected = Style.query
    if query:
        selected = selected.filter(db.or_(Style.name.ilike(f"%{query}%"), Style.description.ilike(f"%{query}%")))
    if category != 'All':
        category_obj = Category.query.filter_by(name=category).first()
        if category_obj:
            selected = selected.filter_by(category_id=category_obj.id)
    styles = selected.order_by(Style.created_at.desc()).all()
    categories = [category.name for category in Category.query.order_by(Category.name).all()]
    return render_template('styles.html', styles=styles, categories=categories, active_category=category)


@app.route('/styles/<slug>')
def style_detail(slug):
    item = Style.query.filter_by(slug=slug).first_or_404()
    related = Style.query.filter(Style.id != item.id).limit(3).all()
    return render_template('style_detail.html', style=item, related_styles=related)


@app.route('/services')
def services_page():
    return render_template('services.html', services=Service.query.all())


@app.route('/booking', methods=['GET', 'POST'])
def booking_page():
    if not session.get('user_id'):
        flash('Please log in or create an account before booking a tailor.', 'error')
        return redirect(url_for('login', next=request.full_path.rstrip('?')))

    if request.method == 'POST':
        customer_name = request.form.get('customer_name', '').strip()
        service_name = request.form.get('service_name', '').strip()
        preferred_date = request.form.get('preferred_date', '').strip()
        preferred_time = request.form.get('preferred_time', '').strip()

        if not all([customer_name, service_name, preferred_date, preferred_time]):
            flash('Please complete all booking fields.', 'error')
            return redirect(url_for('booking_page'))

        booking = Booking(
            user_id=session.get('user_id'),
            customer_name=customer_name,
            service_name=service_name,
            preferred_date=preferred_date,
            preferred_time=preferred_time,
            status='Pending'
        )
        db.session.add(booking)
        db.session.commit()
        flash('Booking submitted successfully. Our team will confirm your appointment.', 'success')
        return redirect(url_for('orders_page'))

    selected_style = request.args.get('style', '').strip()
    return render_template('booking.html', styles=Style.query.limit(5).all(), services=Service.query.all(), selected_style=selected_style)


def generate_order_number():
    while True:
        candidate = f"TAIL-{datetime.utcnow().year}-{secrets.randbelow(900000) + 100000}"
        if not Order.query.filter_by(order_number=candidate).first():
            return candidate


@app.route('/orders/create', methods=['POST'])
@login_required
def create_order():
    if not verify_csrf():
        flash('Your session expired. Please try again.', 'error')
        return redirect(request.referrer or url_for('styles_page'))
    user = current_user()
    style = Style.query.filter_by(slug=request.form.get('style_slug', '').strip()).first()
    if not style:
        flash('That style could not be found.', 'error')
        return redirect(url_for('styles_page'))
    order = Order(
        user_id=user.id,
        order_number=generate_order_number(),
        customer_name=user.full_name,
        item_name=style.name,
        total_amount=style.price,
        status='Order Received',
        delivery_status='Pending',
    )
    db.session.add(order)
    db.session.commit()
    flash(f'Order {order.order_number} placed for {style.name}. Proceed to payment from your dashboard.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/orders')
@login_required
def orders_page():
    user = current_user()
    orders = Order.query.filter(db.or_(Order.user_id == user.id, Order.customer_name == user.full_name)).order_by(Order.created_at.desc()).all()
    return render_template('orders.html', orders=orders)


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next', '') or request.form.get('next', '')
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['user_name'] = user.full_name
            session['role'] = user.role_ref.name
            flash('Login successful.', 'success')
            if user.role_ref.name == 'admin':
                return redirect(url_for('admin'))
            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'error')

    return render_template('login.html', next_url=next_url)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    next_url = request.args.get('next', '') or request.form.get('next', '')
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        if not all([full_name, email, phone, password, confirm_password]):
            flash('Please complete all registration fields.', 'error')
            return render_template('signup.html', next_url=next_url)
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('signup.html', next_url=next_url)
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return render_template('signup.html', next_url=next_url)
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists. Please log in.', 'error')
            return render_template('signup.html', next_url=next_url)
        customer_role = Role.query.filter_by(name='customer').first()
        user = User(
            full_name=full_name,
            email=email,
            phone=phone,
            password_hash=generate_password_hash(password),
            role_id=customer_role.id,
        )
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        session['user_name'] = user.full_name
        session['role'] = customer_role.name
        flash('Your customer account has been created.', 'success')
        if next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('dashboard'))
    return render_template('signup.html', next_url=next_url)


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    user = current_user()
    recent_orders = Order.query.filter(db.or_(Order.user_id == user.id, Order.customer_name == user.full_name)).order_by(Order.created_at.desc()).all()
    bookings = Booking.query.filter(db.or_(Booking.user_id == user.id, Booking.customer_name == user.full_name)).order_by(Booking.created_at.desc()).all()

    order_numbers = [order.order_number for order in recent_orders]
    payments = Payment.query.filter(Payment.order_number.in_(order_numbers)).order_by(Payment.created_at.desc()).all() if order_numbers else []
    measurements = MeasurementRequest.query.filter(db.or_(MeasurementRequest.user_id == user.id, MeasurementRequest.customer_name == user.full_name)).order_by(MeasurementRequest.created_at.desc()).all()

    return render_template('dashboard.html', user=user, orders=recent_orders, bookings=bookings, payments=payments, measurements=measurements, stats={
        'bookings': len(bookings),
        'orders': len(recent_orders),
        'status': recent_orders[0].status if recent_orders else 'No orders yet',
    })


@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = current_user()
    profile_record = user.profile or UserProfile(user_id=user.id)
    if request.method == 'POST':
        if not verify_csrf():
            flash('Your session expired. Please try again.', 'error')
            return redirect(url_for('profile'))
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        if not full_name or not email or not phone:
            flash('Name, email, and phone are required.', 'error')
            return redirect(url_for('profile'))
        duplicate = User.query.filter(User.email == email, User.id != user.id).first()
        if duplicate:
            flash('That email address is already in use.', 'error')
            return redirect(url_for('profile'))
        user.full_name, user.email, user.phone = full_name, email, phone
        profile_record.address = request.form.get('address', '').strip()
        profile_record.city = request.form.get('city', '').strip()
        profile_record.notes = request.form.get('notes', '').strip()
        upload = request.files.get('avatar')
        if upload and upload.filename:
            if not allowed_upload(upload.filename):
                flash('Avatar must be JPG, PNG, or WEBP.', 'error')
                return redirect(url_for('profile'))
            try:
                profile_record.avatar = store_uploaded_image(upload, f"avatar-{user.id}", folder="msadiq/avatars")
            except image_storage.UploadError as e:
                flash(str(e), 'error')
                return redirect(url_for('profile'))
        new_password = request.form.get('password', '')
        if new_password:
            if len(new_password) < 8:
                flash('New password must be at least 8 characters.', 'error')
                return redirect(url_for('profile'))
            user.password_hash = generate_password_hash(new_password)
        db.session.add(profile_record)
        db.session.commit()
        session['user_name'] = user.full_name
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', user=user, profile=profile_record)


@app.route('/payments/<order_number>/initialize', methods=['POST'])
@login_required
def initialize_payment(order_number):
    user = current_user()
    order = Order.query.filter_by(order_number=order_number, customer_name=user.full_name).first_or_404()
    reference = f"MSD-{order.order_number}-{secrets.token_hex(5).upper()}"
    gateway = PaystackGateway(current_app.config['PAYSTACK_SECRET_KEY'], current_app.config['PAYSTACK_CALLBACK_URL'])
    try:
        checkout = gateway.initialize(user.email, order.total_amount * 100, reference)
    except PaymentGatewayError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('dashboard'))
    payment = Payment(order_number=order.order_number, amount=order.total_amount, status='Pending', gateway='Paystack', transaction_reference=reference)
    db.session.add(payment)
    db.session.commit()
    return redirect(checkout.get('authorization_url', url_for('dashboard')))


@app.route('/payments/verify/<reference>')
def verify_payment(reference):
    gateway = PaystackGateway(current_app.config['PAYSTACK_SECRET_KEY'])
    try:
        result = gateway.verify(reference)
    except PaymentGatewayError as exc:
        flash(str(exc), 'error')
        return redirect(url_for('dashboard'))
    payment = Payment.query.filter_by(transaction_reference=reference).first_or_404()
    payment.status = 'Successful' if result.get('status') == 'success' else 'Failed'
    db.session.commit()
    flash('Payment verified successfully.' if payment.status == 'Successful' else 'Payment verification failed.', 'success' if payment.status == 'Successful' else 'error')
    return redirect(url_for('dashboard'))


@app.route('/webhooks/paystack', methods=['POST'])
def paystack_webhook():
    secret = current_app.config['PAYSTACK_SECRET_KEY']
    signature = request.headers.get('x-paystack-signature', '')
    digest = hmac.new(secret.encode(), request.get_data(), hashlib.sha512).hexdigest() if secret else ''
    if not secret or not hmac.compare_digest(signature, digest):
        return jsonify({'error': 'invalid signature'}), 401
    payload = request.get_json(silent=True) or {}
    data = payload.get('data', {})
    payment = Payment.query.filter_by(transaction_reference=data.get('reference')).first()
    if payment and payload.get('event') == 'charge.success':
        payment.status = 'Successful'
        db.session.commit()
    return jsonify({'received': True})


@app.route('/measurements', methods=['POST'])
def measurement_request():
    user = current_user()
    required_fields = ['garment_name', 'chest', 'waist', 'hip', 'sleeve']
    if not all(request.form.get(field, '').strip() for field in required_fields):
        flash('Please complete all measurement fields.', 'error')
        return redirect(url_for('dashboard'))

    measurement = MeasurementRequest(
        user_id=user.id,
        customer_name=user.full_name,
        garment_name=request.form['garment_name'].strip(),
        chest=request.form['chest'].strip(),
        waist=request.form['waist'].strip(),
        hip=request.form['hip'].strip(),
        sleeve=request.form['sleeve'].strip(),
        notes=request.form.get('notes', '').strip(),
    )
    db.session.add(measurement)
    db.session.commit()
    try:
        NotificationService(current_app.config).email(
            user.email,
            'Msadiq Couture measurement request received',
            f'Your measurement request for {measurement.garment_name} has been submitted for review.',
        )
    except Exception:
        app.logger.exception('Measurement notification failed')
    flash('Measurement request submitted for review.', 'success')
    return redirect(url_for('dashboard'))


@app.route('/admin')
@admin_required
def admin():
    query = request.args.get('q', '').strip()
    record_type = request.args.get('record_type', 'all')
    status = request.args.get('status', 'all')
    recent_activity = [
        {"title": "New order #TAIL-2026-000003", "detail": "Signature Jalabiya • Customer: Chinedu Okafor", "time": "12 mins ago"},
        {"title": "Payment update", "detail": "TAIL-2026-000002 • Waiting on Flutterwave confirmation", "time": "1 hour ago"},
        {"title": "Booking confirmed", "detail": "Custom tailoring • Tuesday 10:00 AM", "time": "3 hours ago"}
    ]
    bookings_query = Booking.query
    orders_query = Order.query
    payments_query = Payment.query
    if query:
        bookings_query = bookings_query.filter(db.or_(Booking.customer_name.ilike(f'%{query}%'), Booking.service_name.ilike(f'%{query}%')))
        orders_query = orders_query.filter(db.or_(Order.customer_name.ilike(f'%{query}%'), Order.order_number.ilike(f'%{query}%'), Order.item_name.ilike(f'%{query}%')))
        payments_query = payments_query.filter(db.or_(Payment.order_number.ilike(f'%{query}%'), Payment.transaction_reference.ilike(f'%{query}%')))
    if status != 'all':
        bookings_query = bookings_query.filter_by(status=status)
        orders_query = orders_query.filter_by(status=status)
        payments_query = payments_query.filter_by(status=status)
    bookings = bookings_query.order_by(Booking.created_at.desc()).all()
    orders = orders_query.order_by(Order.created_at.desc()).all()
    payments = payments_query.order_by(Payment.created_at.desc()).all()
    measurements = MeasurementRequest.query.order_by(MeasurementRequest.created_at.desc()).all()
    styles = Style.query.order_by(Style.created_at.desc()).all()
    services = Service.query.order_by(Service.created_at.desc()).all()
    categories = Category.query.order_by(Category.name).all()
    admin_users = User.query.join(Role).filter(Role.name == 'admin').order_by(User.full_name).all()
    analytics = {
        'successful_revenue': sum(payment.amount for payment in Payment.query.filter_by(status='Successful').all()),
        'pending_revenue': sum(payment.amount for payment in Payment.query.filter_by(status='Pending').all()),
        'conversion_rate': round((Order.query.filter(Order.status == 'Completed').count() / Order.query.count()) * 100) if Order.query.count() else 0,
        'top_styles': db.session.query(Order.item_name, db.func.count(Order.id)).group_by(Order.item_name).order_by(db.func.count(Order.id).desc()).limit(5).all(),
    }
    return render_template(
        'admin.html',
        stats=dashboard_stats(),
        recent_activity=recent_activity,
        bookings=bookings,
        orders=orders,
        payments=payments,
        measurements=measurements,
        styles=styles,
        services=services,
        categories=categories,
        admin_users=admin_users,
        analytics=analytics,
        active_page='analytics',
        filters={'q': query, 'record_type': record_type, 'status': status}
    )


def render_admin_resource(page, title, description):
    context = {
        'page': page,
        'title': title,
        'description': description,
        'categories': Category.query.order_by(Category.name).all(),
        'styles': Style.query.order_by(Style.created_at.desc()).all(),
        'services': Service.query.order_by(Service.created_at.desc()).all(),
        'bookings': Booking.query.order_by(Booking.created_at.desc()).all(),
        'orders': Order.query.order_by(Order.created_at.desc()).all(),
        'payments': Payment.query.order_by(Payment.created_at.desc()).all(),
        'admin_users': User.query.join(Role).filter(Role.name.in_(['admin', 'staff'])).order_by(User.full_name).all(),
        'active_page': page,
    }
    return render_template('admin_resource.html', **context)


@app.route('/admin/styles')
@admin_required
def admin_styles():
    return render_admin_resource('styles', 'Styles', 'Manage the Hausa wear styles available in your catalog.')


@app.route('/admin/services')
@admin_required
def admin_services():
    return render_admin_resource('services', 'Services', 'Manage tailoring services and availability.')


@app.route('/admin/booking')
@admin_required
def admin_bookings():
    return render_admin_resource('booking', 'Booking requests', 'Accept or reject customer tailoring appointments.')


@app.route('/admin/payments')
@admin_required
def admin_payments():
    return render_admin_resource('payments', 'Payments', 'Verify customer payments and update their status.')


@app.route('/admin/orders')
@admin_required
def admin_orders():
    return render_admin_resource('orders', 'Orders', 'Approve, respond to, update, or remove customer orders.')


@app.route('/admin/users')
@admin_required
def admin_users():
    return render_admin_resource('admins', 'Manage admin users', 'Create, edit, and remove staff access.')


@app.route('/admin/style/create', methods=['POST'])
@admin_required
def admin_create_style():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Style name is required.', 'error')
        return redirect(url_for('admin_styles'))

    category_id = request.form.get('category_id', type=int)
    price = request.form.get('price', type=int)
    description = request.form.get('description', '').strip()
    colors = request.form.get('colors', '').strip()
    fabrics = request.form.get('fabrics', '').strip()
    lead_time = request.form.get('lead_time', '10-14 days').strip()
    availability = request.form.get('availability', 'Made to order').strip()
    image_main = request.form.get('image_main', '').strip() or 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=900&q=80'
    image_upload = request.files.get('image_file')
    if image_upload and image_upload.filename:
        if not allowed_upload(image_upload.filename):
            flash('Style image must be JPG, PNG, or WEBP.', 'error')
            return redirect(url_for('admin_styles'))
        try:
            image_main = store_uploaded_image(image_upload, "style", folder="msadiq/styles")
        except image_storage.UploadError as e:
            flash(str(e), 'error')
            return redirect(url_for('admin_styles'))
    image_gallery = request.form.get('image_gallery', '').strip() or image_main

    style = Style(
        name=name,
        slug=unique_style_slug(request.form.get('slug', ''), name),
        category_id=category_id or 1,
        gender=request.form.get('gender', 'Women'),
        price=price or 150000,
        featured='featured' in request.form,
        new_arrival='new_arrival' in request.form,
        description=description or 'Luxury tailored piece crafted for modern elegance.',
        colors=colors or 'Gold|Ivory',
        fabrics=fabrics or 'Premium cotton|Silk blend',
        lead_time=lead_time,
        availability=availability,
        image_main=image_main,
        image_gallery=image_gallery,
        rating=4.8,
        reviews=0
    )
    db.session.add(style)
    db.session.commit()
    flash('Style created successfully.', 'success')
    return redirect(url_for('admin_styles'))


@app.route('/admin/service/create', methods=['POST'])
@admin_required
def admin_create_service():
    name = request.form.get('name', '').strip()
    if not name:
        flash('Service name is required.', 'error')
        return redirect(url_for('admin_services'))

    image = request.form.get('image', '').strip() or 'https://images.unsplash.com/photo-1521572267360-ee0c2909d518?auto=format&fit=crop&w=900&q=80'
    image_upload = request.files.get('image_file')
    if image_upload and image_upload.filename:
        if not allowed_upload(image_upload.filename):
            flash('Service image must be JPG, PNG, or WEBP.', 'error')
            return redirect(url_for('admin_services'))
        try:
            image = store_uploaded_image(image_upload, "service", folder="msadiq/services")
        except image_storage.UploadError as e:
            flash(str(e), 'error')
            return redirect(url_for('admin_services'))

    service = Service(
        name=name,
        description=request.form.get('description', '').strip() or 'Tailoring service for premium finishes and personalization.',
        price=request.form.get('price', type=int) or 50000,
        duration=request.form.get('duration', '7-10 days').strip(),
        status=request.form.get('status', 'Available').strip(),
        image=image
    )
    db.session.add(service)
    db.session.commit()
    flash('Service added successfully.', 'success')
    return redirect(url_for('admin_services'))


@app.route('/admin/booking/<int:booking_id>/status', methods=['POST'])
@admin_required
def admin_update_booking_status(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = request.form.get('status', booking.status)
    db.session.commit()
    notify_customer(booking.customer_name, 'Msadiq Couture booking update', f'Your {booking.service_name} booking is now {booking.status}.')
    flash('Booking status updated.', 'success')
    return redirect(url_for('admin_bookings'))


@app.route('/admin/order/<int:order_id>/status', methods=['POST'])
@admin_required
def admin_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    order.status = request.form.get('status', order.status)
    order.delivery_status = request.form.get('delivery_status', order.delivery_status)
    order.admin_response = request.form.get('admin_response', order.admin_response).strip()
    db.session.commit()
    notify_customer(order.customer_name, 'Msadiq Couture order update', f'Order {order.order_number}: production status is {order.status}; delivery status is {order.delivery_status}.')
    flash('Order status updated.', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/order/<int:order_id>/delete', methods=['POST'])
@admin_required
def admin_delete_order(order_id):
    order = Order.query.get_or_404(order_id)
    Payment.query.filter_by(order_number=order.order_number).delete()
    db.session.delete(order)
    db.session.commit()
    flash('Order deleted.', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/payment/<int:payment_id>/status', methods=['POST'])
@admin_required
def admin_update_payment_status(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    payment.status = request.form.get('status', payment.status)
    db.session.commit()
    flash('Payment status updated.', 'success')
    return redirect(url_for('admin_payments'))


@app.route('/admin/booking/<int:booking_id>/delete', methods=['POST'])
@admin_required
def admin_delete_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()
    flash('Booking request deleted.', 'success')
    return redirect(url_for('admin_bookings'))


@app.route('/admin/payment/<int:payment_id>/delete', methods=['POST'])
@admin_required
def admin_delete_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    db.session.delete(payment)
    db.session.commit()
    flash('Payment record deleted.', 'success')
    return redirect(url_for('admin_payments'))


@app.route('/admin/style/<int:style_id>/delete', methods=['POST'])
@admin_required
def admin_delete_style(style_id):
    style = Style.query.get_or_404(style_id)
    db.session.delete(style)
    db.session.commit()
    flash('Style deleted.', 'success')
    return redirect(url_for('admin_styles'))


@app.route('/admin/style/<int:style_id>/edit', methods=['POST'])
@admin_required
def admin_edit_style(style_id):
    style = Style.query.get_or_404(style_id)
    style.name = request.form.get('name', style.name).strip() or style.name
    if 'slug' in request.form:
        # Only touch the slug if the form actually sent one (the inline
        # edit form doesn't); an empty value falls back to the name.
        style.slug = unique_style_slug(request.form.get('slug', ''), style.name, exclude_id=style.id)
    style.price = request.form.get('price', type=int) or style.price
    style.description = request.form.get('description', style.description).strip()
    style.availability = request.form.get('availability', style.availability).strip()
    style.lead_time = request.form.get('lead_time', style.lead_time).strip() or style.lead_time
    style.colors = request.form.get('colors', style.colors).strip() or style.colors
    style.fabrics = request.form.get('fabrics', style.fabrics).strip() or style.fabrics
    if request.form.get('category_id', type=int):
        style.category_id = request.form.get('category_id', type=int)
    if request.form.get('gender'):
        style.gender = request.form.get('gender')
    # The quick inline form (name/price only) doesn't send these checkboxes at
    # all, so only touch them when the submitting form actually has the
    # checkbox fields - otherwise a quick save was silently unchecking both.
    if 'style_full_edit' in request.form:
        style.featured = 'featured' in request.form
        style.new_arrival = 'new_arrival' in request.form
    image_url = request.form.get('image_main', '').strip()
    if image_url:
        style.image_main = image_url
        style.image_gallery = image_url
    image_upload = request.files.get('image_file')
    if image_upload and image_upload.filename:
        if not allowed_upload(image_upload.filename):
            flash('Style image must be JPG, PNG, or WEBP.', 'error')
            return redirect(url_for('admin_styles'))
        try:
            style.image_main = store_uploaded_image(image_upload, "style", folder="msadiq/styles")
        except image_storage.UploadError as e:
            flash(str(e), 'error')
            return redirect(url_for('admin_styles'))
        style.image_gallery = style.image_main
    db.session.commit()
    flash('Style updated.', 'success')
    return redirect(url_for('admin_styles'))


@app.route('/admin/service/<int:service_id>/delete', methods=['POST'])
@admin_required
def admin_delete_service(service_id):
    service = Service.query.get_or_404(service_id)
    db.session.delete(service)
    db.session.commit()
    flash('Service deleted.', 'success')
    return redirect(url_for('admin_services'))


@app.route('/admin/user/create', methods=['POST'])
@admin_required
def admin_create_user():
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    password = request.form.get('password', '')
    role_name = request.form.get('role', 'admin')
    if not all([full_name, email, phone, password]):
        flash('Complete all admin user fields.', 'error')
        return redirect(url_for('admin_users'))
    if User.query.filter_by(email=email).first():
        flash('That email is already registered.', 'error')
        return redirect(url_for('admin_users'))
    role = Role.query.filter_by(name=role_name).first_or_404()
    db.session.add(User(full_name=full_name, email=email, phone=phone, password_hash=generate_password_hash(password), role_id=role.id))
    db.session.commit()
    flash('Admin user created.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/edit', methods=['POST'])
@admin_required
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)
    user.full_name = request.form.get('full_name', user.full_name).strip() or user.full_name
    user.phone = request.form.get('phone', user.phone).strip() or user.phone
    role = Role.query.filter_by(name=request.form.get('role', user.role_ref.name)).first()
    if role:
        user.role_id = role.id
    password = request.form.get('password', '')
    if password:
        user.password_hash = generate_password_hash(password)
    db.session.commit()
    flash('Admin user updated.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    if user_id == session.get('user_id'):
        flash('You cannot delete your own active account.', 'error')
        return redirect(url_for('admin_users'))
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    flash('Admin user deleted.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/customers')
@admin_required
def admin_customers():
    query = request.args.get('q', '').strip()
    customers_query = User.query.join(Role).filter(Role.name == 'customer')
    if query:
        customers_query = customers_query.filter(db.or_(
            User.full_name.ilike(f'%{query}%'),
            User.email.ilike(f'%{query}%'),
            User.phone.ilike(f'%{query}%'),
        ))
    customers = customers_query.order_by(User.full_name).all()
    return render_template(
        'admin_customers.html',
        customers=customers,
        query=query,
        active_page='customers',
    )


@app.route('/admin/customers/<int:user_id>')
@admin_required
def admin_customer_detail(user_id):
    customer = User.query.join(Role).filter(Role.name == 'customer', User.id == user_id).first_or_404()
    orders = Order.query.filter(db.or_(Order.user_id == customer.id, Order.customer_name == customer.full_name)).order_by(Order.created_at.desc()).all()
    bookings = Booking.query.filter(db.or_(Booking.user_id == customer.id, Booking.customer_name == customer.full_name)).order_by(Booking.created_at.desc()).all()
    measurements = MeasurementRequest.query.filter(db.or_(MeasurementRequest.user_id == customer.id, MeasurementRequest.customer_name == customer.full_name)).order_by(MeasurementRequest.created_at.desc()).all()
    return render_template(
        'admin_customer_detail.html',
        customer=customer,
        orders=orders,
        bookings=bookings,
        measurements=measurements,
        active_page='customers',
    )


@app.route('/admin/customers/<int:user_id>/edit', methods=['POST'])
@admin_required
def admin_edit_customer(user_id):
    customer = User.query.join(Role).filter(Role.name == 'customer', User.id == user_id).first_or_404()
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    phone = request.form.get('phone', '').strip()
    if not full_name or not email or not phone:
        flash('Name, email, and phone are required.', 'error')
        return redirect(url_for('admin_customer_detail', user_id=customer.id))
    duplicate = User.query.filter(User.email == email, User.id != customer.id).first()
    if duplicate:
        flash('That email address is already in use.', 'error')
        return redirect(url_for('admin_customer_detail', user_id=customer.id))
    customer.full_name, customer.email, customer.phone = full_name, email, phone
    profile_record = customer.profile or UserProfile(user_id=customer.id)
    profile_record.address = request.form.get('address', '').strip()
    profile_record.city = request.form.get('city', '').strip()
    profile_record.notes = request.form.get('notes', '').strip()
    password = request.form.get('password', '')
    if password:
        customer.password_hash = generate_password_hash(password)
    db.session.add(profile_record)
    db.session.commit()
    flash('Customer details updated.', 'success')
    return redirect(url_for('admin_customer_detail', user_id=customer.id))


@app.route('/admin/customers/<int:user_id>/delete', methods=['POST'])
@admin_required
def admin_delete_customer(user_id):
    customer = User.query.join(Role).filter(Role.name == 'customer', User.id == user_id).first_or_404()
    db.session.delete(customer)
    db.session.commit()
    flash('Customer deleted.', 'success')
    return redirect(url_for('admin_customers'))


@app.route('/admin/service/<int:service_id>/edit', methods=['POST'])
@admin_required
def admin_edit_service(service_id):
    service = Service.query.get_or_404(service_id)
    service.name = request.form.get('name', service.name).strip() or service.name
    service.description = request.form.get('description', service.description).strip()
    service.price = request.form.get('price', type=int) or service.price
    service.duration = request.form.get('duration', service.duration).strip()
    service.status = request.form.get('status', service.status).strip()
    image_url = request.form.get('image', '').strip()
    if image_url:
        service.image = image_url
    image_upload = request.files.get('image_file')
    if image_upload and image_upload.filename:
        if not allowed_upload(image_upload.filename):
            flash('Service image must be JPG, PNG, or WEBP.', 'error')
            return redirect(url_for('admin_services'))
        try:
            service.image = store_uploaded_image(image_upload, "service", folder="msadiq/services")
        except image_storage.UploadError as e:
            flash(str(e), 'error')
            return redirect(url_for('admin_services'))
    db.session.commit()
    flash('Service updated.', 'success')
    return redirect(url_for('admin_services'))


if __name__ == '__main__':
    app.run(
        debug=os.environ.get('FLASK_DEBUG', '0') == '1',
        host='0.0.0.0',
        port=int(os.environ.get('PORT', '5000')),
    )
