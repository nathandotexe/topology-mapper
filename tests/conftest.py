import pytest

from topo_mapper.connections import MockLab, bundled_demo_lab


@pytest.fixture
def demo_lab() -> MockLab:
    return MockLab(bundled_demo_lab())


@pytest.fixture
def demo_dir():
    return bundled_demo_lab()
