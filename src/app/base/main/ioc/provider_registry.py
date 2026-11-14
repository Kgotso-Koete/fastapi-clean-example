from collections.abc import Iterable, Sequence

from dishka import Provider

from app.base.main.ioc.core import CoreProvider
from app.base.main.ioc.outbound import CeleryProvider, outbound_providers
from app.base.main.modules import UNITS, Unit, check_needs, collect_providers


def get_providers(units: Sequence[Unit] = UNITS) -> Iterable[Provider]:
    # The registry's start-up check (docs/plans/16-modular-monolith.md, user
    # story 4): building the container is the first thing the app does, so a
    # unit whose need isn't registered stops it here, before it serves anything.
    check_needs(units)
    return (
        # The same units again: CoreProvider subscribes handlers only from them,
        # so nothing is subscribed that collect_providers below didn't bind.
        CoreProvider(units),
        *outbound_providers(),
        CeleryProvider(),
        # Every registered unit's web providers, in registration order
        # (docs/plans/16-modular-monolith.md, "The registry").
        *collect_providers(unit.WEB_PROVIDERS for unit in units),
    )
