from . import data
from . import models


def build_demo_company(env):
    """Build the Naqaa company after install. Idempotent."""
    env['alshayeb.demo.builder'].build_all()
