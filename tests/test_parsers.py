from topo_mapper.parsers import (
    parse_cdp_detail,
    parse_hostname,
    parse_interface_status,
    parse_ip_interface_brief,
    parse_lldp_detail,
    parse_platform,
)
from topo_mapper.roles import infer_role


def _read(demo_dir, host, cmd):
    return (demo_dir / host / f"{cmd}.txt").read_text(encoding="utf-8")


def test_cdp_parse_core1(demo_dir):
    records = parse_cdp_detail(_read(demo_dir, "core1", "show_cdp_neighbors_detail"))
    assert len(records) == 3
    by_device = {r.remote_device: r for r in records}

    dist1 = by_device["dist1.lab.local"]
    assert dist1.local_interface == "GigabitEthernet0/0"
    assert dist1.remote_interface == "GigabitEthernet0/1"
    assert dist1.mgmt_ip == "10.0.0.2"
    assert "Switch" in dist1.capabilities
    assert dist1.protocol == "cdp"

    edge = by_device["edge-fw"]
    assert edge.mgmt_ip == "10.0.0.254"
    assert infer_role(edge.capabilities) == "router"


def test_cdp_parse_phone_without_mgmt_ip(demo_dir):
    records = parse_cdp_detail(_read(demo_dir, "access1", "show_cdp_neighbors_detail"))
    phone = next(r for r in records if r.remote_device == "SEP001122334455")
    assert phone.mgmt_ip is None
    assert phone.local_interface == "GigabitEthernet0/5"
    assert infer_role(phone.capabilities) == "endpoint"


def test_lldp_parse_dist1(demo_dir):
    records = parse_lldp_detail(_read(demo_dir, "dist1", "show_lldp_neighbors_detail"))
    assert len(records) == 3
    core = next(r for r in records if r.remote_device == "core1.lab.local")
    assert core.local_interface == "GigabitEthernet0/1"
    assert core.remote_interface == "GigabitEthernet0/0"
    assert core.mgmt_ip == "10.0.0.1"
    assert core.protocol == "lldp"


def test_interface_status_parse(demo_dir):
    states = parse_interface_status(_read(demo_dir, "dist1", "show_interfaces_status"))
    assert states["GigabitEthernet0/1"]["status"] == "up"
    assert states["GigabitEthernet0/10"]["status"] == "down"


def test_interface_status_with_name_column(demo_dir):
    states = parse_interface_status(_read(demo_dir, "access1", "show_interfaces_status"))
    assert states["GigabitEthernet0/5"]["status"] == "up"
    assert states["GigabitEthernet0/5"]["vlan"] == "10"


def test_ip_interface_brief_parse():
    text = (
        "Interface              IP-Address      OK? Method Status                Protocol\n"
        "GigabitEthernet0/0     10.0.0.1        YES NVRAM  up                    up\n"
        "GigabitEthernet0/1     unassigned      YES unset  administratively down down\n"
    )
    states = parse_ip_interface_brief(text)
    assert states["GigabitEthernet0/0"]["status"] == "up"
    assert states["GigabitEthernet0/1"]["status"] == "down"


def test_hostname_and_platform(demo_dir):
    version = _read(demo_dir, "core1", "show_version")
    assert parse_hostname(version) == "core1"
    assert parse_platform(version).startswith("Cisco IOS Software")


def test_empty_input_is_safe():
    assert parse_cdp_detail("") == []
    assert parse_lldp_detail("") == []
    assert parse_interface_status("") == {}
