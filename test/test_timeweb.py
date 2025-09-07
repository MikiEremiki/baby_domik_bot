import os
import pytest
from requests import Response

# Mark entire module as integration tests
pytestmark = pytest.mark.integration

# Optionally skip the whole module if TIMEWEB_TOKEN is not provided via env
# to avoid accidental live HTTP in CI/local runs.
if not os.environ.get('TIMEWEB_TOKEN'):
    pytest.skip("Skipping Timeweb integration tests: token not configured in TIMEWEB_TOKEN", allow_module_level=True)


@pytest.fixture()
def response():
    """Perform a real HTTP request to Timeweb API using configured token."""
    # Lazy import to avoid importing src.api.timeweb when skipping the module
    from src.api.timeweb import request_finances_info
    return request_finances_info()


def test_is_response(response):
    assert isinstance(response, Response)


def test_ok_response(response):
    assert response.status_code == 200


def test_is_int(response):
    assert isinstance(response.json()['finances']['hours_left'], int)

