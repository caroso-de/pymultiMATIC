import json
from datetime import date, timedelta
from typing import Any, AsyncGenerator, Dict, List, Tuple, Type
from unittest import mock

import pytest
from aiohttp import ClientSession
from aioresponses import aioresponses

from pymultimatic.api import ApiError, Connector, WrongResponseError, payloads, urls
from pymultimatic.model import OperatingModes, QuickModes, QuickVeto, constants, mapper
from pymultimatic.systemmanager import SystemManager, retry_async
from tests.conftest import mock_auth, path

SERIAL = mapper.map_serial_number(json.loads(open(path("files/responses/facilities")).read()))


@pytest.fixture(name="resp", autouse=True)
async def fixture_resp(resp: aioresponses) -> AsyncGenerator[aioresponses, None]:
    with open(path("files/responses/facilities"), "r") as file:
        facilities = json.loads(file.read())
        resp.get(urls.facilities_list(), payload=facilities, status=200)
    yield resp


@pytest.fixture(name="manager")
async def fixture_manager(
    session: ClientSession, connector: Connector
) -> AsyncGenerator[SystemManager, None]:
    manager = SystemManager("user", "pass", session, "pymultiMATIC", SERIAL)
    await connector.login()
    with mock.patch.object(connector, "request", wraps=connector.request):
        manager._connector = connector
        yield manager


@pytest.mark.asyncio
async def test_system(manager: SystemManager, resp: aioresponses) -> None:
    with open(path("files/responses/livereport"), "r") as file:
        livereport_data = json.loads(file.read())

    with open(path("files/responses/rooms"), "r") as file:
        rooms_data = json.loads(file.read())

    with open(path("files/responses/systemcontrol"), "r") as file:
        system_data = json.loads(file.read())

    with open(path("files/responses/hvacstate"), "r") as file:
        hvacstate_data = json.loads(file.read())

    with open(path("files/responses/facilities"), "r") as file:
        facilities = json.loads(file.read())

    with open(path("files/responses/gateway"), "r") as file:
        gateway = json.loads(file.read())

    _mock_urls(
        resp,
        hvacstate_data,
        livereport_data,
        rooms_data,
        system_data,
        facilities,
        gateway,
    )

    system = await manager.get_system()

    assert system is not None

    assert len(system.zones) == 2
    assert len(system.rooms) == 4
    _assert_calls(6, manager)
    assert manager._fixed_serial


@pytest.mark.asyncio
async def test_get_hot_water(manager: SystemManager, resp: aioresponses) -> None:
    with open(path("files/responses/hotwater"), "r") as file:
        raw_hotwater = json.loads(file.read())

    dhw_url = urls.hot_water(id="Control_DHW", serial=SERIAL)
    resp.get(dhw_url, payload=raw_hotwater, status=200)

    hot_water = await manager.get_hot_water("Control_DHW")

    assert hot_water is not None
    _assert_calls(1, manager, [dhw_url])


@pytest.mark.asyncio
async def test_set_hot_water_setpoint_temperature(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.hot_water_temperature_setpoint(id="id", serial=SERIAL)
    payload = payloads.hotwater_temperature_setpoint(60.0)

    resp.put(url, status=200)

    await manager.set_hot_water_setpoint_temperature("id", 60)

    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_set_hot_water_setpoint_temp_number_to_round(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.hot_water_temperature_setpoint(serial=SERIAL, id="id")
    payload = payloads.hotwater_temperature_setpoint(60.5)

    resp.put(url, status=200)

    await manager.set_hot_water_setpoint_temperature("id", 60.4)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_set_quick_mode_no_current_quick_mode(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.system_quickmode(serial=SERIAL)
    payload = payloads.quickmode(QuickModes.VENTILATION_BOOST.name)

    resp.put(url, status=200)

    await manager.set_quick_mode(QuickModes.VENTILATION_BOOST)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_logout(manager: SystemManager) -> None:
    await manager.logout()
    _assert_calls(1, manager, [urls.logout()])


@pytest.mark.asyncio
async def test_set_quick_veto_room(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.room_quick_veto(serial=SERIAL, id="1")

    quick_veto = QuickVeto(100, 25)
    resp.put(url, status=200)

    await manager.set_room_quick_veto("1", quick_veto)
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_hot_water_operation_mode_wrong_mode(manager: SystemManager) -> None:
    await manager.set_hot_water_operating_mode("hotwater", OperatingModes.NIGHT)

    _assert_calls(0, manager)


@pytest.mark.asyncio
async def test_set_hot_water_operation_mode_heating_mode(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.hot_water_operating_mode(serial=SERIAL, id="hotwater")

    resp.put(url, status=200)
    await manager.set_hot_water_operating_mode("hotwater", OperatingModes.ON)
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_quick_veto_zone(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.zone_quick_veto(id="Zone1", serial=SERIAL)

    quick_veto = QuickVeto(duration=100, target=25)
    resp.put(url, status=200)

    await manager.set_zone_quick_veto("Zone1", quick_veto)
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_room_operation_mode_heating_mode(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.room_operating_mode(id="1", serial=SERIAL)
    print(url)

    resp.put(url, status=200)
    await manager.set_room_operating_mode("1", OperatingModes.AUTO)
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_room_operation_mode_no_new_mode(manager: SystemManager) -> None:
    await manager.set_room_operating_mode("1", None)
    _assert_calls(0, manager)


@pytest.mark.asyncio
async def test_set_room_operation_mode_wrong_mode(manager: SystemManager) -> None:
    await manager.set_room_operating_mode("1", OperatingModes.NIGHT)


@pytest.mark.asyncio
async def test_set_zone_operation_mode_heating_mode(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.zone_heating_mode(id="Zone1", serial=SERIAL)

    resp.put(url, status=200)
    await manager.set_zone_heating_operating_mode("Zone1", OperatingModes.AUTO)
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_zone_operation_mode_no_new_mode(manager: SystemManager) -> None:
    await manager.set_zone_heating_operating_mode("Zone1", None)
    _assert_calls(0, manager)


@pytest.mark.asyncio
async def test_set_zone_operation_mode_no_zone(manager: SystemManager) -> None:
    await manager.set_zone_heating_operating_mode(None, OperatingModes.MANUAL)
    _assert_calls(0, manager)


@pytest.mark.asyncio
async def test_get_room(manager: SystemManager, resp: aioresponses) -> None:
    with open(path("files/responses/room"), "r") as file:
        raw_rooms = json.loads(file.read())

    resp.get(urls.room(id="1", serial=SERIAL), payload=raw_rooms, status=200)

    new_room = await manager.get_room("1")
    assert new_room is not None


@pytest.mark.asyncio
async def test_get_zone(manager: SystemManager, resp: aioresponses) -> None:
    with open(path("files/responses/zone"), "r") as file:
        raw_zone = json.loads(file.read())

    url = urls.zone(serial=SERIAL, id="Control_ZO2")
    resp.get(url, payload=raw_zone, status=200)

    new_zone = await manager.get_zone("Control_ZO2")
    assert new_zone is not None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_circulation(manager: SystemManager, resp: aioresponses) -> None:
    with open(path("files/responses/circulation"), "r") as file:
        raw_circulation = json.loads(file.read())

    url = urls.circulation(id="id_dhw", serial=SERIAL)
    resp.get(url, payload=raw_circulation, status=200)

    new_circulation = await manager.get_circulation("id_dhw")
    assert new_circulation is not None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_set_room_setpoint_temperature(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.room_temperature_setpoint(id="1", serial=SERIAL)
    payload = payloads.room_temperature_setpoint(22.0)
    resp.put(url, status=200)

    await manager.set_room_setpoint_temperature("1", 22)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_set_zone_setpoint_temperature(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.zone_heating_setpoint_temperature(id="Zone1", serial=SERIAL)
    payload = payloads.zone_temperature_setpoint(25.5)

    resp.put(url, status=200)

    await manager.set_zone_heating_setpoint_temperature("Zone1", 25.5)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_set_zone_setback_temperature(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.zone_heating_setback_temperature(id="Zone1", serial=SERIAL)
    payload = payloads.zone_temperature_setback(18.0)

    resp.put(url, status=200)

    await manager.set_zone_heating_setback_temperature("Zone1", 18)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_set_holiday_mode(manager: SystemManager, resp: aioresponses) -> None:
    tomorrow = date.today() + timedelta(days=1)
    after_tomorrow = tomorrow + timedelta(days=1)

    url = urls.system_holiday_mode(serial=SERIAL)
    resp.put(url, status=200)
    payload = payloads.holiday_mode(True, tomorrow, after_tomorrow, 15.0)

    await manager.set_holiday_mode(tomorrow, after_tomorrow, 15)
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_remove_holiday_mode(manager: SystemManager, resp: aioresponses) -> None:
    yesterday = date.today() - timedelta(days=1)
    before_yesterday = yesterday - timedelta(days=1)

    url = urls.system_holiday_mode(serial=SERIAL)
    resp.put(url, status=200)
    payload = payloads.holiday_mode(
        False, before_yesterday, yesterday, constants.FROST_PROTECTION_TEMP
    )

    await manager.remove_holiday_mode()
    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_remove_zone_quick_veto(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.zone_quick_veto(id="id", serial=SERIAL)
    resp.delete(url, status=200)

    await manager.remove_zone_quick_veto("id")
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_remove_room_quick_veto(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.room_quick_veto(id="1", serial=SERIAL)
    resp.delete(url, status=200)

    await manager.remove_room_quick_veto("1")
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_request_hvac_update(manager: SystemManager, resp: aioresponses) -> None:
    url_update = urls.hvac_update(serial=SERIAL)
    resp.put(url_update, status=200)

    with open(path("files/responses/hvacstate"), "r") as file:
        hvacstate_data = json.loads(file.read())

    url_hvac = urls.hvac(serial=SERIAL)
    resp.get(url_hvac, payload=hvacstate_data, status=200)

    await manager.request_hvac_update()

    _assert_calls(2, manager, [url_hvac, url_update])


@pytest.mark.asyncio
async def test_request_hvac_not_sync(manager: SystemManager, resp: aioresponses) -> None:
    url_update = urls.hvac_update(serial=SERIAL)
    resp.put(url_update, status=200)

    with open(path("files/responses/hvacstate_pending"), "r") as file:
        hvacstate_data = json.loads(file.read())

    url_hvac = urls.hvac(serial=SERIAL)
    resp.get(url_hvac, payload=hvacstate_data, status=200)

    await manager.request_hvac_update()
    _assert_calls(1, manager, [url_hvac])


@pytest.mark.asyncio
async def test_remove_quick_mode(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_quickmode(serial=SERIAL)
    resp.delete(url, status=200)

    await manager.remove_quick_mode()
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_remove_quick_mode_no_active_quick_mode(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.system_quickmode(serial=SERIAL)
    resp.delete(url, status=409)

    await manager.remove_quick_mode()
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_remove_quick_mode_error(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_quickmode(serial=SERIAL)
    resp.delete(url, status=400)

    try:
        await manager.remove_quick_mode()
        raise AssertionError("Error expected")
    except ApiError as exc:
        assert exc.status == 400

    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_quick_veto_temperature_room_rounded(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.room_quick_veto(id="0", serial=SERIAL)
    payload = payloads.room_quick_veto(22.5, 180)
    resp.put(url, status=200)

    qveto = QuickVeto(180, 22.7)
    await manager.set_room_quick_veto("0", qveto)

    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_quick_veto_temperature_zone_rounded(
    manager: SystemManager, resp: aioresponses
) -> None:
    url = urls.zone_quick_veto(id="zone1", serial=SERIAL)
    payload = payloads.zone_quick_veto(22.5)
    resp.put(url, status=200)

    qveto = QuickVeto(duration=35, target=22.7)
    await manager.set_zone_quick_veto("zone1", qveto)

    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_holiday_mode_temperature_rounded(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_holiday_mode(serial=SERIAL)
    resp.put(url, status=200)

    tomorrow = date.today() + timedelta(days=1)
    after_tomorrow = tomorrow + timedelta(days=1)

    payload = payloads.holiday_mode(True, tomorrow, after_tomorrow, 22.5)

    await manager.set_holiday_mode(tomorrow, after_tomorrow, 22.7)

    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_serial_not_fixed(session: ClientSession) -> None:
    manager = SystemManager("user", "pass", session, "pymultiMATIC")
    assert not manager._fixed_serial


@pytest.mark.asyncio
async def test_serial_not_fixed_login(session: ClientSession, resp: aioresponses) -> None:
    manager = SystemManager("user", "pass", session, "pymultiMATIC")

    with open(path("files/responses/zone"), "r") as file:
        raw_zone = json.loads(file.read())

    url = urls.zone(serial=SERIAL, id="zone")
    resp.get(url, payload=raw_zone, status=200)

    await manager.get_zone("zone")
    assert manager._serial == SERIAL
    assert not manager._fixed_serial


@pytest.mark.asyncio
async def test_serial_not_fixed_relogin(
    session: ClientSession, connector: Connector, resp: aioresponses
) -> None:
    manager = SystemManager("user", "pass", session, "pymultiMATIC")

    with open(path("files/responses/zone"), "r") as file:
        raw_zone = json.loads(file.read())

    with open(path("files/responses/facilities"), "r") as file:
        facilities = json.loads(file.read())

    facilities["body"]["facilitiesList"][0]["serialNumber"] = "123"

    url_zone1 = urls.zone(serial=SERIAL, id="zone")
    url_zone2 = urls.zone(serial="123", id="zone")

    url_facilities = urls.facilities_list(serial=SERIAL)

    resp.get(url_zone1, payload=raw_zone, status=200)
    resp.get(url_zone2, payload=raw_zone, status=200)
    resp.get(url_facilities, payload=facilities, status=200)

    mock_auth(resp)

    await manager.get_zone("zone")
    assert manager._serial == SERIAL
    assert not manager._fixed_serial

    connector._clear_cookies()

    await manager.get_zone("zone")
    assert manager._serial == "123"


@pytest.mark.asyncio
async def test_login(session: ClientSession) -> None:
    manager = SystemManager("user", "pass", session, "pymultiMATIC")
    assert await manager.login()


@pytest.mark.asyncio
async def test_logout_serial_not_fixed(session: ClientSession) -> None:
    manager = SystemManager("user", "pass", session, "pymultiMATIC")
    assert await manager.login()
    await manager.logout()
    assert manager._serial is None


@pytest.mark.asyncio
async def test_set_ventilation_operating_mode(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.set_ventilation_operating_mode(
        serial=SERIAL,
        id="123",
    )
    resp.put(url, status=200)

    payload = payloads.ventilation_operating_mode("OFF")

    await manager.set_ventilation_operating_mode("123", OperatingModes.OFF)

    _assert_calls(1, manager, [url], [payload])


@pytest.mark.asyncio
async def test_get_gateway(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.gateway_type(
        serial=SERIAL,
    )
    with open(path("files/responses/gateway"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    gateway = await manager.get_gateway()
    assert gateway == "VR920"
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_quickmode(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_quickmode(
        serial=SERIAL,
    )
    with open(path("files/responses/quick_mode"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    quickmode = await manager.get_quick_mode()
    assert quickmode == QuickModes.SYSTEM_OFF
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_quickmode_no_quickmode(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_quickmode(
        serial=SERIAL,
    )

    resp.get(url, status=409)

    quickmode = await manager.get_quick_mode()
    assert quickmode is None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_outdoor_temperature(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_status(
        serial=SERIAL,
    )

    with open(path("files/responses/systemstatus"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    temp = await manager.get_outdoor_temperature()
    assert temp == 12.5
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_hvac_status(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.hvac(
        serial=SERIAL,
    )

    with open(path("files/responses/hvacstate"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    await manager.get_hvac_status()
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_facility_detail_no_serial(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.facilities_list(
        serial=SERIAL,
    )

    with open(path("files/responses/facilities"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    details = await manager.get_facility_detail()
    assert details.serial_number == SERIAL
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_facility_detail_other_serial(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.facilities_list(
        serial=SERIAL,
    )

    with open(path("files/responses/facilities_multiple"), "r") as file:
        json_raw = json.loads(file.read())

    key = None
    for match in resp._matches.items():
        if match[1].url_or_pattern.path in urls.facilities_list():
            key = match[0]
    resp._matches.pop(key)
    resp.get(url, status=200, payload=json_raw)

    details = await manager.get_facility_detail("888")
    assert details.serial_number == "888"
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_live_reports(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.live_report(
        serial=SERIAL,
    )

    with open(path("files/responses/livereport"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    reports = await manager.get_live_reports()
    assert reports is not None and len(reports) > 0
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_live_report(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.live_report_device(serial=SERIAL, report_id="1", device_id="2")

    with open(path("files/responses/livereport_single"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    reports = await manager.get_live_report("1", "2")
    assert reports is not None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_holiday_mode(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_holiday_mode(
        serial=SERIAL,
    )

    with open(path("files/responses/holiday_mode"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    await manager.get_holiday_mode()
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_rooms(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.rooms(
        serial=SERIAL,
    )

    with open(path("files/responses/rooms"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    rooms = await manager.get_rooms()
    assert rooms is not None and len(rooms) > 0
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_dhw(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.dhws(
        serial=SERIAL,
    )

    with open(path("files/responses/dhws"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    dhw = await manager.get_dhw()
    assert dhw.hotwater is not None and dhw.circulation is not None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_zones(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.zones(
        serial=SERIAL,
    )

    with open(path("files/responses/zones"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    zones = await manager.get_zones()
    assert zones is not None and len(zones) > 0
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_ventilation(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.system_ventilation(
        serial=SERIAL,
    )

    with open(path("files/responses/ventilation"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    ventilation = await manager.get_ventilation()
    assert ventilation is not None
    _assert_calls(1, manager, [url])


@pytest.mark.asyncio
async def test_get_emf_devices(manager: SystemManager, resp: aioresponses) -> None:
    url = urls.emf_devices(
        serial=SERIAL,
    )

    with open(path("files/responses/emf_devices"), "r") as file:
        json_raw = json.loads(file.read())

    resp.get(url, status=200, payload=json_raw)

    emf_reports = await manager.get_emf_devices()
    assert emf_reports is not None
    assert len(emf_reports) == 7
    _assert_calls(1, manager, [url])


def _mock_urls(
    resp: aioresponses,
    hvacstate_data: Any,
    livereport_data: Any,
    rooms_data: Any,
    system_data: Any,
    facilities: Any = None,
    gateway: Any = None,
) -> None:
    resp.get(urls.live_report(serial=SERIAL), payload=livereport_data, status=200)
    resp.get(urls.rooms(serial=SERIAL), payload=rooms_data, status=200)
    resp.get(urls.system(serial=SERIAL), payload=system_data, status=200)
    resp.get(urls.hvac(serial=SERIAL), payload=hvacstate_data, status=200)

    if facilities:
        resp.get(urls.facilities_list(), payload=facilities, status=200)

    if gateway:
        resp.get(urls.gateway_type(serial=SERIAL), payload=gateway, status=200)


def _assert_calls(
    count: int,
    manager: SystemManager,
    expected_urls: List[str] = None,
    expected_payloads: List[Any] = None,
) -> None:
    calls = manager._connector.request.call_args_list  # type: ignore
    assert count == len(calls)

    actual_urls: List[str] = []
    actual_payloads: List[Dict[str, Any]] = []

    for call in calls:
        (args, kwargs) = call
        actual_urls.append(args[1])
        actual_payloads.append(args[2])

    if expected_urls:
        diff = [x for x in expected_urls if x not in actual_urls]
        assert not diff

    if expected_payloads:
        diff = [x for x in expected_payloads if x not in actual_payloads]
        assert not diff


def _api_error(status: int) -> ApiError:
    return ApiError(message="api error", response="blah", status=status)


def _wrong_response_error(status: int) -> ApiError:
    return WrongResponseError(message="api error", response="blah", status=status)


@pytest.mark.parametrize(
    "on_exceptions, on_status_codes, exception, should_retry, expect_ex",
    [
        ((ValueError,), (), ValueError(), True, _api_error(500)),
        ((ValueError,), (), IndexError(), False, IndexError()),
        ((ValueError,), (500,), IndexError(), False, IndexError()),
        ((ValueError,), (), _api_error(400), False, _api_error(400)),
        ((ValueError,), (500,), _api_error(400), False, _api_error(400)),
        (
            (WrongResponseError,),
            (200,),
            _wrong_response_error(200),
            True,
            _api_error(200),
        ),
    ],
)
@pytest.mark.asyncio
async def test_retry_async(
    on_exceptions: Tuple[Type[BaseException]],
    on_status_codes: Tuple[int],
    exception: Type[BaseException],
    should_retry: bool,
    expect_ex: Type[BaseException],
) -> None:
    cnt = {"cnt": 0}
    num_tries = 3

    @retry_async(
        num_tries=num_tries,
        on_exceptions=on_exceptions,
        on_status_codes=on_status_codes,
        backoff_base=0,
    )
    async def func() -> None:
        cnt["cnt"] += 1
        raise exception

    with pytest.raises(expect_ex.__class__):  # type: ignore
        await func()

    assert cnt["cnt"] == (num_tries if should_retry else 1)
