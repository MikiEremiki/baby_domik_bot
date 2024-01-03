from unittest import TestCase
from requests import Response
from components.api.timeweb import request_finances_info

response = request_finances_info()


class TestTimeWeb(TestCase):
    def test_is_response(self):
        self.assertIsInstance(response, Response)

    def test_ok_response(self):
        self.assertEquals(response.status_code, 200)

    def test_is_int(self):
        self.assertIsInstance(response.json()['finances']['hours_left'], int)

