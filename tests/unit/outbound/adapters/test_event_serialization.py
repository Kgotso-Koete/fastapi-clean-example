from app.core.common.events.user_registered import UserRegisteredEvent
from app.outbound.adapters.event_serialization import dotted_path, import_from_dotted_path


class TestDottedPath:
    """
    dotted_path()/import_from_dotted_path() let a Celery message carry a
    plain string identifying which event/handler class to use, instead of
    the class object itself (which can't cross a process boundary as JSON).
    """

    def test_dotted_path_of_a_real_event_class(self) -> None:
        path = dotted_path(UserRegisteredEvent)

        # "module:QualName" -- the colon separator (rather than another dot)
        # makes it unambiguous where the module path ends and the class
        # name begins, even for nested classes.
        assert path == "app.core.common.events.user_registered:UserRegisteredEvent"

    def test_import_from_dotted_path_is_the_inverse_of_dotted_path(self) -> None:
        path = dotted_path(UserRegisteredEvent)

        imported = import_from_dotted_path(path)

        # Reconstructing from the dotted path should give back the exact
        # same class object we started with, not just an equivalent one.
        assert imported is UserRegisteredEvent
