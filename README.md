# Msadiq Couture Platform

A premium luxury tailoring marketplace and business management system inspired by the provided product brief. The project combines a public storefront with customer-facing browsing and a simple admin dashboard for business operations.

## Brand identity

The official brand logo from the workspace is integrated into the interface and used in the site header, footer, and login experience.

## Features included

- Public homepage with luxury white-and-gold fashion styling
- Marketplace catalog with category filters and search
- Style detail pages with image gallery and pricing
- Services landing page
- About, contact, login, and admin views
- Business overview dashboard for management KPIs
- Customer profiles, avatar uploads, measurements, payments, and order tracking
- Admin style/service CRUD, booking/order/payment status operations
- Paystack checkout initialization and signed webhook verification
- SMTP email and Twilio SMS adapters, enabled only with environment credentials
- CSRF protection, secure session cookies, upload limits, and role-based access
- Responsive layout designed for desktop and mobile screens

## Tech stack

- Python 3.12+
- Flask 3.1
- Flask-SQLAlchemy
- Gunicorn
- HTML
- CSS
- JavaScript

## Project structure

- app.py: application routes and sample data
- templates/: HTML pages
- static/css/styles.css: styling system
- static/js/app.js: small client-side interactions
- static/images/logo.png: client logo asset

## Run locally

1. Open a terminal in this folder.
2. Install dependencies:
   python -m pip install -r requirements.txt
3. Copy `.env.example` to `.env` and set a unique `SECRET_KEY`.
4. Start the app:
   python app.py
5. Open http://localhost:5000

## Production

Set `DATABASE_URL`, `SECRET_KEY`, `SESSION_COOKIE_SECURE=1`, and the optional
Paystack, SMTP, and Twilio credentials from `.env.example`. Start with:

   gunicorn --workers 3 --bind 0.0.0.0:$PORT wsgi:application

Production startup does not seed demo records. Run the seed only in local
development with `SEED_DEMO_DATA=1`. Configure the hosting platform health
check to request `/healthz`; it returns HTTP 200 only when the database is
reachable.

The included `Dockerfile` and `Procfile` use the same WSGI entrypoint. Persist
the `instance/` database and `static/uploads/` storage, or replace them with
managed database/object storage before a multi-instance deployment.

## Tests

   python -m pytest -q

## Notes

The application uses environment-backed integrations. Payment, email, and SMS
calls remain disabled until their credentials are configured; this prevents a
local or staging environment from sending real messages or charging customers.
