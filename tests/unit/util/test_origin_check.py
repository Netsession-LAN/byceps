"""Netsession: writing requests from foreign sites are refused (CSRF
protection on top of SameSite cookies)."""

from flask import Flask
import pytest

from byceps.util import origin_check


@pytest.fixture
def client():
    app = Flask(__name__)
    origin_check.register(app)

    @app.route('/form', methods=['GET', 'POST'])
    def form():
        return 'ok'

    return app.test_client()


URL = 'http://www.example.test/form'


def test_same_origin_post_passes(client):
    response = client.post(URL, headers={'Origin': 'https://www.example.test'})
    assert response.status_code == 200


def test_foreign_origin_post_is_refused(client):
    response = client.post(URL, headers={'Origin': 'https://evil.test'})
    assert response.status_code == 403


def test_null_origin_post_is_refused(client):
    response = client.post(URL, headers={'Origin': 'null'})
    assert response.status_code == 403


def test_foreign_referer_without_origin_is_refused(client):
    response = client.post(URL, headers={'Referer': 'https://evil.test/page'})
    assert response.status_code == 403


def test_post_without_origin_and_referer_passes(client):
    # e.g. server-to-server callbacks of payment providers
    assert client.post(URL).status_code == 200


def test_foreign_origin_get_passes(client):
    response = client.get(URL, headers={'Origin': 'https://evil.test'})
    assert response.status_code == 200
