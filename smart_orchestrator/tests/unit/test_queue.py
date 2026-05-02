import pytest
import asyncio
import fakeredis.aioredis as fakeredis
from unittest.mock import AsyncMock, MagicMock, patch

from app.lib.queue import enqueue_job, store_result, get_result, STREAM_KEY, RESULT_PREFIX


@pytest.fixture
def redis():
    return fakeredis.FakeRedis()


@pytest.mark.asyncio
async def test_enqueue_returns_job_id(redis):
    job_id = await enqueue_job(redis, {"prompt": "hello", "tier": "free"})
    assert job_id
    assert isinstance(job_id, str)
    assert len(job_id) > 0


@pytest.mark.asyncio
async def test_store_and_get_result(redis):
    job_id = "1234-test"
    await store_result(redis, job_id, {"status": "done", "result": "hello world", "model": "llama", "tokens": "5"})
    result = await get_result(redis, job_id, timeout=1)
    assert result is not None
    assert result["status"] == "done"
    assert result["result"] == "hello world"


@pytest.mark.asyncio
async def test_get_result_timeout(redis):
    result = await get_result(redis, "nonexistent-job-xyz", timeout=0)
    assert result is None


@pytest.mark.asyncio
async def test_worker_processes_job(redis):
    from app.worker import process_job

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test answer"
    with patch("app.worker.classify_prompt_simple", new_callable=AsyncMock, return_value="chat"), \
            patch("app.worker.call_with_escalation", new_callable=AsyncMock,
                  return_value=(mock_response, "llama-3.1-8b", 10)), \
            patch("app.worker.record_usage", new_callable=AsyncMock):

        await process_job(redis, "job-1", {"prompt": "hi", "key_hash": "abc123"})

        result = await get_result(redis, "job-1", timeout=1)
        assert result is not None
        assert result["status"] == "done"
