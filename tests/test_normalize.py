import pytest

from topo_mapper.normalize import device_key, normalize_hostname, normalize_interface


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Gi0/1", "GigabitEthernet0/1"),
        ("gi0/1", "GigabitEthernet0/1"),
        ("GigabitEthernet0/1", "GigabitEthernet0/1"),
        ("Te1/0/1", "TenGigabitEthernet1/0/1"),
        ("Fa0/24", "FastEthernet0/24"),
        ("Eth1/1", "Ethernet1/1"),
        ("Po12", "Port-channel12"),
        ("Loopback0", "Loopback0"),
        ("mgmt0", "Management0"),
        ("weird9", "weird9"),
    ],
)
def test_normalize_interface(raw, expected):
    assert normalize_interface(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SW1.lab.local", "SW1"),
        ("SW1(FDO1234ABCD)", "SW1"),
        ("core-1.example.com ", "core-1"),
        ("10.0.0.1", "10.0.0.1"),
        ("R1 description here", "R1"),
    ],
)
def test_normalize_hostname(raw, expected):
    assert normalize_hostname(raw) == expected


def test_keep_domain():
    assert normalize_hostname("SW1.lab.local", keep_domain=True) == "SW1.lab.local"


def test_device_key_is_case_insensitive():
    assert device_key("Core1.LAB.local") == device_key("core1")
