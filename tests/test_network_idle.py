"""NetworkInterceptor exposes an in-flight counter for real network-idle waits."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _add_src(src_on_path):
    yield


@pytest.mark.asyncio
async def test_in_flight_counter_increments_and_decrements():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    assert ni.in_flight_count("inst-1") == 0
    ni._inc_in_flight("inst-1")
    ni._inc_in_flight("inst-1")
    assert ni.in_flight_count("inst-1") == 2
    ni._dec_in_flight("inst-1")
    assert ni.in_flight_count("inst-1") == 1
    ni._dec_in_flight("inst-1")
    ni._dec_in_flight("inst-1")  # never goes negative
    assert ni.in_flight_count("inst-1") == 0


@pytest.mark.asyncio
async def test_wait_for_idle_resolves_when_counter_drops():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    ni._inc_in_flight("inst-1")

    async def drop_later():
        await asyncio.sleep(0.05)
        ni._dec_in_flight("inst-1")

    asyncio.create_task(drop_later())
    settled = await ni.wait_for_idle("inst-1", idle_ms=50, timeout_ms=2000)
    assert settled is True


@pytest.mark.asyncio
async def test_wait_for_idle_times_out_when_traffic_never_settles():
    from network_interceptor import NetworkInterceptor

    ni = NetworkInterceptor()
    ni._inc_in_flight("inst-1")

    settled = await ni.wait_for_idle("inst-1", idle_ms=50, timeout_ms=200)
    assert settled is False
