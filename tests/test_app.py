import re

import pytest

from app import app, db, MeasurementRequest


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


def test_invalid_csrf_is_rejected(client):
    response = client.post('/login', data={'email': 'admin@msadiq.com', 'password': 'admin123'})
    assert response.status_code == 400


def test_customer_can_submit_measurement(client):
    response = login(client, 'aisha@msadiq.com', 'customer123')
    assert response.status_code == 200
    token = csrf(client)
    response = client.post('/measurements', data={
        'csrf_token': token,
        'garment_name': 'Test Kaftan',
        'chest': '38 in',
        'waist': '32 in',
        'hip': '40 in',
        'sleeve': '24 in',
    }, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context():
        assert MeasurementRequest.query.filter_by(garment_name='Test Kaftan').count() == 1
