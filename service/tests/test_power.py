"""The power menu on the TV (DESIGN_CORRECTIONS_2.md, part 9)."""

from fastapi.testclient import TestClient

from dabox.limits_service import FakePower
from dabox.services import Services
from tests.conftest import FakeAgent


def test_shut_down_stops_what_plays_then_powers_off(
    box_client: TestClient, completed_setup: None, fake_agent: FakeAgent, fake_power: FakePower, services: Services,
) -> None:
    fake_agent.play("game", "Rocket")
    assert services.box_state.parent_mode is False
    assert box_client.post("/box/power/off").status_code == 200
    assert fake_agent.stopped == 1
    assert fake_power.powered_off


def test_the_network_cannot_shut_the_box_down(phone_client: TestClient, fake_power: FakePower) -> None:
    assert phone_client.post("/box/power/off").status_code == 403
    assert not fake_power.powered_off
