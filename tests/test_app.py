import re

import pytest

from app import app, db, ContactMessage, MeasurementRequest, Service, Style


@pytest.fixture()
def client(tmp_path):
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=True,
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
        SECRET_KEY="test-secret",
        PAYSTACK_SECRET_KEY="",
    )
    with app.test_client() as test_client:
        yield test_client


def csrf(client):
    response = client.get('/login')
    token = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert token
    return token.group(1).decode()


def login(client, email, password):
    token = csrf(client)
    return client.post('/login', data={'csrf_token': token, 'email': email, 'password': password}, follow_redirects=True)


def test_public_homepage_and_protected_dashboard(client):
    assert client.get('/').status_code == 200
    assert client.get('/dashboard').status_code == 302


def test_served_stylesheet_has_responsive_public_and_account_layouts(client):
    response = client.get('/static/css/styles.css')
    assert response.status_code == 200
    css = response.data
    for rule in (
        b'@media (max-width: 1024px)',
        b'@media (max-width: 720px)',
        b'@media (max-width: 480px)',
        b'.admin-sidebar-nav a { flex: 0 0 auto; white-space: nowrap; }',
        b'.table-wrap { max-width: 100%; overflow-x: auto; }',
        b'.footer-grid { grid-template-columns: repeat(2, minmax(0, 1fr));',
    ):
        assert rule in css


def test_invalid_csrf_is_rejected(client):
    response = client.post('/login', data={'email': 'admin@msadiq.com', 'password': 'admin123'})
    assert response.status_code == 400


def test_contact_messages_are_saved_and_admin_can_view_them(client):
    contact_page = client.get('/contact')
    assert contact_page.status_code == 200
    assert b'No. 265, Giginyu - A, Sala Kaapani Road' in contact_page.data
    token = csrf(client)
    response = client.post('/contact', data={
        'csrf_token': token,
        'name': 'Test Customer',
        'email': 'customer@example.com',
        'message': 'I would like to discuss a bespoke outfit.',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Your message has been sent' in response.data

    with app.app_context():
        assert ContactMessage.query.filter_by(email='customer@example.com').count() == 1

    login(client, 'admin@msadiq.com', 'admin123')
    response = client.get('/admin/messages')
    assert response.status_code == 200
    assert b'I would like to discuss a bespoke outfit.' in response.data


def test_style_promotion_is_saved_and_shown_on_cards(client):
    login(client, 'admin@msadiq.com', 'admin123')
    style_admin_page = client.get('/admin/styles')
    assert b'<select name="promotion">' in style_admin_page.data
    assert b'20%' in style_admin_page.data
    token = csrf(client)
    response = client.post('/admin/style/create', data={
        'csrf_token': token,
        'name': 'Promotion Test Style',
        'slug': 'promotion-test-style',
        'category_id': '1',
        'gender': 'Women',
        'price': '100000',
        'promotion': '20',
        'featured': 'on',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        style = Style.query.filter_by(slug='promotion-test-style').one()
        assert style.promotion == 20
    response = client.get('/')
    assert b'20% OFF' in response.data


def test_service_admin_forms_hide_price_status_and_image_url_fields(client):
    login(client, 'admin@msadiq.com', 'admin123')
    response = client.get('/admin/services')
    assert response.status_code == 200
    assert b'name="price"' not in response.data
    assert b'name="status"' not in response.data
    assert b'name="image"' not in response.data


def test_admin_and_customer_pages_have_centered_headings_and_no_back_arrows(client):
    login(client, 'admin@msadiq.com', 'admin123')
    admin_page = client.get('/admin/services')
    assert b'>Dashboard</a>' in admin_page.data
    assert b'>Analytics</a>' not in admin_page.data
    assert b'Back to dashboard' not in admin_page.data
    assert b'class="admin-page-heading"' in admin_page.data
    stylesheet = client.get('/static/css/styles.css')
    assert b'.admin-page-heading { max-width: 760px; margin: 0 auto 32px; text-align: center; }' in stylesheet.data
    client.get('/logout', follow_redirects=True)
    login(client, 'aisha@msadiq.com', 'customer123')
    customer_page = client.get('/orders')
    assert b'Back to dashboard' not in customer_page.data
    assert b'Track your tailoring journey' in customer_page.data


def test_homepage_shows_at_most_four_service_cards(client):
    with app.app_context():
        db.session.add_all([
            Service(
                name=f'Homepage test service {index}',
                description='Service used to verify the homepage card limit.',
                price=50000,
                duration='7-10 days',
                status='Available',
                image='https://example.com/service.jpg',
            )
            for index in range(5)
        ])
        db.session.commit()
    response = client.get('/')
    assert response.status_code == 200
    assert response.data.count(b'class="service-card"') == 4
    assert b'images/Hero.jpg' in response.data
    assert b'View more services' in response.data
    assert b'href="/contact">Contact</a>' in response.data


def test_customer_can_submit_measurement(client):
    response = login(client, 'aisha@msadiq.com', 'customer123')
    assert response.status_code == 200
    measurement_page = client.get('/measurements')
    assert b'<select name="garment_name" required>' in measurement_page.data
    assert b'Bespoke tailoring' in measurement_page.data
    assert b'Ready to wears' in measurement_page.data
    assert b'Bridal Wears' in measurement_page.data
    assert b'Monogram' not in measurement_page.data
    token = csrf(client)
    response = client.post('/measurements', data={
        'csrf_token': token,
        'garment_name': 'Bespoke tailoring',
        'chest': '38 in',
        'waist': '32 in',
        'hip': '40 in',
        'sleeve': '24 in',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert MeasurementRequest.query.filter_by(garment_name='Bespoke tailoring').count() == 1
