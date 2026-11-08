import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from nats.js.api import StreamConfig
from nats.js.errors import NotFoundError
from api.nats_migrate import run_nats_migration, REQUIRED_SUBJECTS, STREAM_NAME


def test_nats_migrate_create_stream_when_not_found():
    mock_nc = MagicMock()
    mock_nc.close = AsyncMock()
    mock_jsm = MagicMock()
    mock_jsm.stream_info = AsyncMock(side_effect=NotFoundError)
    mock_jsm.add_stream = AsyncMock()
    mock_jsm.consumer_info = AsyncMock(side_effect=NotFoundError)
    mock_jsm.add_consumer = AsyncMock()
    mock_nc.jsm.return_value = mock_jsm

    with patch("nats.connect", AsyncMock(return_value=mock_nc)):
        res = asyncio.run(run_nats_migration(url="nats://localhost:4222"))

    assert res["created_stream"] is True
    assert res["updated_stream"] is False
    assert set(res["added_subjects"]) == set(REQUIRED_SUBJECTS)
    assert mock_jsm.add_stream.called
    assert mock_jsm.add_consumer.call_count == len(REQUIRED_SUBJECTS)


def test_nats_migrate_update_stream_missing_subjects():
    mock_nc = MagicMock()
    mock_nc.close = AsyncMock()
    mock_jsm = MagicMock()
    existing_config = StreamConfig(
        name=STREAM_NAME,
        subjects=["yookassa", "gspread"]
    )
    mock_info = MagicMock()
    mock_info.config = existing_config
    mock_jsm.stream_info = AsyncMock(return_value=mock_info)
    mock_jsm.update_stream = AsyncMock()
    mock_jsm.consumer_info = AsyncMock()
    mock_jsm.add_consumer = AsyncMock()
    mock_nc.jsm.return_value = mock_jsm

    with patch("nats.connect", AsyncMock(return_value=mock_nc)):
        res = asyncio.run(run_nats_migration(url="nats://localhost:4222"))

    assert res["created_stream"] is False
    assert res["updated_stream"] is True
    assert "schedule_sync_result" in res["added_subjects"]
    assert "sales" in res["added_subjects"]
    assert mock_jsm.update_stream.called
    assert set(res["all_subjects"]) == set(REQUIRED_SUBJECTS)


def test_nats_migrate_no_update_when_all_subjects_present():
    mock_nc = MagicMock()
    mock_nc.close = AsyncMock()
    mock_jsm = MagicMock()
    existing_config = StreamConfig(
        name=STREAM_NAME,
        subjects=list(REQUIRED_SUBJECTS)
    )
    mock_info = MagicMock()
    mock_info.config = existing_config
    mock_jsm.stream_info = AsyncMock(return_value=mock_info)
    mock_jsm.update_stream = AsyncMock()
    mock_jsm.add_stream = AsyncMock()
    mock_jsm.consumer_info = AsyncMock()
    mock_jsm.add_consumer = AsyncMock()
    mock_nc.jsm.return_value = mock_jsm

    with patch("nats.connect", AsyncMock(return_value=mock_nc)):
        res = asyncio.run(run_nats_migration(url="nats://localhost:4222"))

    assert res["created_stream"] is False
    assert res["updated_stream"] is False
    assert res["added_subjects"] == []
    assert not mock_jsm.update_stream.called
    assert not mock_jsm.add_stream.called
