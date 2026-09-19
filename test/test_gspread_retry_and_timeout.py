import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import requests
import gspread.exceptions

from api.googlesheets import RetryingClientManager, _agcm
from api.gspread_worker import handle_gspread_task


def make_api_error(status_code: int, text: str = "Error"):
    mock_response = MagicMock(spec=requests.Response)
    mock_response.status_code = status_code
    mock_response.text = text
    mock_response.json.return_value = {"error": {"message": text, "code": status_code}}
    return gspread.exceptions.APIError(mock_response)


def test_retrying_client_manager_config():
    assert _agcm.gspread_timeout == (10.0, 60.0)
    assert _agcm.max_retries == 3


def test_call_success_first_attempt():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=3)
        mock_func = MagicMock(return_value="success_data")

        res = await cm._call(mock_func, "arg1", key="val")
        assert res == "success_data"
        assert mock_func.call_count == 1

    asyncio.run(_test())


def test_call_retry_on_request_exception_then_success():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=3)
        mock_func = MagicMock(
            side_effect=[requests.exceptions.ReadTimeout("Timeout error"), "recovered_data"]
        )

        res = await cm._call(mock_func)
        assert res == "recovered_data"
        assert mock_func.call_count == 2

    asyncio.run(_test())


def test_call_max_retries_exceeded_requests_exception():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=3)
        mock_func = MagicMock(
            side_effect=requests.exceptions.ConnectionError("Connection refused")
        )

        with pytest.raises(requests.exceptions.ConnectionError):
            await cm._call(mock_func)

        # Initial attempt + 3 retries = 4 attempts total
        assert mock_func.call_count == 4

    asyncio.run(_test())


def test_call_api_error_400_fatal_not_retried():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=3)
        err_400 = make_api_error(400, "Bad Request")
        mock_func = MagicMock(side_effect=err_400)

        with pytest.raises(gspread.exceptions.APIError):
            await cm._call(mock_func)

        # Fatal error should raise immediately on first attempt
        assert mock_func.call_count == 1

    asyncio.run(_test())


def test_call_api_error_429_retried_and_recovers():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=3)
        err_429 = make_api_error(429, "Rate limit exceeded")
        mock_func = MagicMock(side_effect=[err_429, "ok_after_rate_limit"])

        res = await cm._call(mock_func)
        assert res == "ok_after_rate_limit"
        assert mock_func.call_count == 2

    asyncio.run(_test())


def test_call_api_error_500_max_retries_exceeded():
    async def _test():
        cm = RetryingClientManager(lambda: None, gspread_delay=0.01, max_retries=2)
        err_500 = make_api_error(500, "Internal Server Error")
        mock_func = MagicMock(side_effect=err_500)

        with pytest.raises(gspread.exceptions.APIError):
            await cm._call(mock_func)

        # Initial attempt + 2 retries = 3 attempts total
        assert mock_func.call_count == 3

    asyncio.run(_test())


def test_gspread_worker_escalation_on_error():
    async def _test():
        mock_logger = MagicMock()
        data = {
            'action': 'update_ticket',
            'sheet_id': 'sheet123',
            'ticket_id': 100,
            'status': 'Оплачен',
            'option': 1,
        }

        with patch('api.gspread_worker.update_ticket_in_gspread', AsyncMock(side_effect=RuntimeError("Google sheet update failed"))), \
             patch('api.gspread_worker.broker.publish', AsyncMock()) as mock_publish:

            await handle_gspread_task(data, mock_logger)

            mock_publish.assert_awaited_once_with(
                data, subject='gspread_failed', stream='baby_domik'
            )

    asyncio.run(_test())
