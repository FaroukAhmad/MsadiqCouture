"""One-time setup for a fresh database (run from your own machine).

    set DATABASE_URL=postgresql://...        (your Neon / hosted Postgres URL)
    set ADMIN_EMAIL=you@example.com
    set ADMIN_PASSWORD=a-long-unique-password
    python init_db.py

Creates the tables, the three roles, the default categories, and (optionally)
the first admin account. Safe to re-run: existing rows are left alone.
"""
import os
import sys

from werkzeug.security import generate_password_hash

from app import app, db, Role, User, Category


def main():
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if email and len(password) < 12:
        sys.exit("ADMIN_PASSWORD must be at least 12 characters.")

    with app.app_context():
        db.create_all()
        for name in ("customer", "staff", "admin"):
            if not Role.query.filter_by(name=name).first():
                db.session.add(Role(name=name))
        for name, slug in [
            ("Traditional Wear", "traditional-wear"),
            ("Corporate Wear", "corporate-wear"),
            ("Wedding Wear", "wedding-wear"),
            ("Modern Wear", "modern-wear"),
        ]:
            if not Category.query.filter_by(slug=slug).first():
                db.session.add(Category(name=name, slug=slug))
        db.session.commit()

        if email:
            if User.query.filter_by(email=email).first():
                print(f"Admin {email} already exists - left unchanged.")
            else:
                admin_role = Role.query.filter_by(name="admin").first()
                db.session.add(User(
                    full_name=os.environ.get("ADMIN_NAME", "Msadiq Administrator"),
                    email=email,
                    phone=os.environ.get("ADMIN_PHONE", "0000000000"),
                    password_hash=generate_password_hash(password),
                    role_id=admin_role.id,
                ))
                db.session.commit()
                print(f"Created admin {email}.")
        print("Database ready on:", db.engine.url.render_as_string(hide_password=True))


if __name__ == "__main__":
    main()
