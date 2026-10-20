from topo_mapper.discovery import Discoverer
from topo_mapper.exporters import to_simple_html
from topo_mapper.graph import build_snapshot


def _snapshot(demo_lab):
    result = Discoverer(demo_lab.factory()).run(demo_lab.seeds)
    return build_snapshot(result, demo_lab.seeds)


def test_report_lists_every_device_and_link(demo_lab):
    snapshot = _snapshot(demo_lab)
    page = to_simple_html(snapshot)

    for dev in snapshot["devices"]:
        assert dev["label"] in page
    assert page.count("<tr>") == len(snapshot["devices"]) + len(snapshot["links"]) + 2
    assert "failed" in page  # edge-fw is unreachable in the demo lab
    assert "<script" not in page


def test_report_escapes_untrusted_values():
    snapshot = {
        "devices": [
            {"name": "x", "label": "<img src=x onerror=alert(1)>", "errors": ["<b>boom</b>"]}
        ],
        "links": [],
    }
    page = to_simple_html(snapshot)
    assert "<img" not in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page
    assert "&lt;b&gt;boom&lt;/b&gt;" in page
