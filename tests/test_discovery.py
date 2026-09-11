from topo_mapper.discovery import Discoverer
from topo_mapper.graph import build_graph, build_snapshot


def _run(demo_lab, **kwargs):
    discoverer = Discoverer(demo_lab.factory(), **kwargs)
    return discoverer.run(demo_lab.seeds)


def test_full_walk_discovers_every_device(demo_lab):
    result = _run(demo_lab)
    assert set(result.devices) == {
        "core1",
        "dist1",
        "dist2",
        "access1",
        "access2",
        "edge-fw",
        "sep001122334455",
    }


def test_unreachable_neighbor_is_a_partial_node(demo_lab):
    result = _run(demo_lab)
    edge = result.devices["edge-fw"]
    assert edge.reachable is False
    assert edge.role == "router"
    assert edge.errors  # a connection error was recorded
    assert result.failed == ["10.0.0.254"]


def test_links_are_deduplicated_and_bidirectional(demo_lab):
    result = _run(demo_lab)
    # 7 physical links: 3 off core1, dist1<->dist2, dist1<->access1,
    # dist2<->access2, access1<->phone
    assert len(result.links) == 7

    core_dist1 = result.links[
        ("core1", "GigabitEthernet0/0", "dist1", "GigabitEthernet0/1")
    ]
    assert core_dist1.protocols == frozenset({"cdp", "lldp"})


def test_cdp_only_link_has_single_protocol(demo_lab):
    result = _run(demo_lab)
    edge_link = result.links[
        ("core1", "GigabitEthernet0/2", "edge-fw", "GigabitEthernet0/0")
    ]
    assert edge_link.protocols == frozenset({"cdp"})


def test_protocol_filter_lldp_only_skips_phone_and_edge(demo_lab):
    result = _run(demo_lab, protocols=("lldp",))
    assert "sep001122334455" not in result.devices  # phone is CDP-only
    assert "edge-fw" not in result.devices  # edge-fw is CDP-only


def test_max_devices_caps_the_walk(demo_lab):
    result = _run(demo_lab, max_devices=1)
    assert len(result.scanned) == 1


def test_enrich_attaches_interface_state_and_link_status(demo_lab):
    result = _run(demo_lab, enrich=True)
    assert result.devices["dist1"].interfaces["GigabitEthernet0/1"]["status"] == "up"
    graph = build_graph(result)
    assert graph["core1"]["dist1"]["status"] == "up"


def test_snapshot_shape(demo_lab):
    result = _run(demo_lab)
    snap = build_snapshot(result, demo_lab.seeds)
    assert snap["stats"] == {
        "devices": 7,
        "reachable": 5,
        "failed": 1,  # edge-fw
        "not_scanned": 1,  # the IP phone (leaf, never probed)
        "links": 7,
        "endpoints": 1,
    }
    assert snap["devices"] == sorted(snap["devices"], key=lambda d: d["name"])


def test_graph_build(demo_lab):
    graph = build_graph(_run(demo_lab))
    assert graph.number_of_nodes() == 7
    assert graph.number_of_edges() == 7
    assert graph.nodes["core1"]["role"] == "l3-switch"
