import shutil
import subprocess
from pathlib import Path

import pytest

# The repository root: this file is tests/base/unit/main/test_makefile_test_paths.py.
_REPO_ROOT = Path(__file__).resolve().parents[4]

# Every make call below spells out /usr/bin/make (where Debian, Ubuntu and macOS
# install it) and its arguments as literals, so ruff's subprocess rules can see
# exactly what runs (S603, S607). The Docker test image has no make (checked
# 2026-11-04), so under `make test-docker` these tests are reported as skipped
# (pytest shows the reason below only with -rs); `make check` runs them on the
# host every time.
pytestmark = pytest.mark.skipif(
    not Path("/usr/bin/make").exists(),
    reason="make is not installed at /usr/bin/make (the Docker test image has none)",
)


def _copy_makefile(workdir: Path) -> None:
    # The tests run `make -n` against a copy of the real Makefile in a
    # temporary folder, next to fake module test folders, so nothing in the
    # repository is touched and nothing is run (-n only prints the commands).
    shutil.copy(_REPO_ROOT / "Makefile", workdir / "Makefile")


def _add_module_test_folders(workdir: Path, *folders: str) -> None:
    # Fake test folders for two modules, as their tests would sit under
    # tests/modules/<name>/ (docs/plans/16-modular-monolith.md, Decision 10).
    for module in ("notifications", "organizations"):
        for folder in folders:
            (workdir / "tests" / "modules" / module / folder).mkdir(parents=True)


def test_make_test_runs_every_modules_unit_tests(tmp_path: Path) -> None:
    # `make test` (the light tests `make check` runs) must pick up every
    # module's unit tests without the Makefile naming the module (user story 5).
    _add_module_test_folders(tmp_path, "unit")
    _copy_makefile(tmp_path)

    result = subprocess.run(["/usr/bin/make", "-n", "test"], cwd=tmp_path, capture_output=True, text=True, check=True)

    assert "tests/modules/notifications/unit" in result.stdout
    assert "tests/modules/organizations/unit" in result.stdout


def test_make_test_docker_app_runs_every_modules_unit_and_infrastructure_tests(tmp_path: Path) -> None:
    # `make test-docker-app` (the Docker test run) must pick up every module's
    # unit tests and its infrastructure tests, the same way.
    _add_module_test_folders(tmp_path, "unit", "integration/with_infra")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker-app"], cwd=tmp_path, capture_output=True, text=True, check=True
    )

    assert "tests/modules/notifications/unit" in result.stdout
    assert "tests/modules/notifications/integration/with_infra" in result.stdout
    assert "tests/modules/organizations/unit" in result.stdout
    assert "tests/modules/organizations/integration/with_infra" in result.stdout


def _add_shared_test_folders(workdir: Path, *folders: str) -> None:
    # Fake test folders for shared, as its tests sit under tests/shared/
    # (docs/plans/16-modular-monolith.md, Decision 17's mirroring rule): next to
    # tests/modules/, not inside it, so the modules' wildcard can't see them.
    for folder in folders:
        (workdir / "tests" / "shared" / folder).mkdir(parents=True)


def test_make_test_runs_shareds_unit_tests(tmp_path: Path) -> None:
    # `make test` (the light tests `make check` runs) must pick up shared's unit
    # tests too, or a shared test would pass on its own and never run in make check.
    _add_shared_test_folders(tmp_path, "unit")
    _copy_makefile(tmp_path)

    result = subprocess.run(["/usr/bin/make", "-n", "test"], cwd=tmp_path, capture_output=True, text=True, check=True)

    assert "tests/shared/unit" in result.stdout


def test_make_test_docker_app_runs_shareds_unit_and_infrastructure_tests(tmp_path: Path) -> None:
    # `make test-docker-app` (the Docker test run) must pick up shared's unit
    # tests and its infrastructure tests, the same way.
    _add_shared_test_folders(tmp_path, "unit", "integration/with_infra")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker-app"], cwd=tmp_path, capture_output=True, text=True, check=True
    )

    assert "tests/shared/unit" in result.stdout
    assert "tests/shared/integration/with_infra" in result.stdout


# Each unit's own top test folder (Decision 10's mirroring rule). A run narrowed to
# one unit with `unit=<name>` (O6) must name none of the other units' folders.
_UNIT_FOLDERS = {
    "base": "tests/base/",
    "notifications": "tests/modules/notifications/",
    "organizations": "tests/modules/organizations/",
    "shared": "tests/shared/",
}


def _assert_names_no_other_unit(output: str, unit: str) -> None:
    # Fails naming the first other unit's folder the run would also test.
    for other, folder in _UNIT_FOLDERS.items():
        if other != unit:
            assert folder not in output, f"unit={unit} also runs {folder}"


def test_make_check_with_a_unit_tests_only_that_unit(tmp_path: Path) -> None:
    # `make check unit=organizations` still lints the whole app (the import rules are
    # about the whole graph), but runs only Organizations' light tests.
    _add_module_test_folders(tmp_path, "unit")
    _add_shared_test_folders(tmp_path, "unit")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "check", "unit=organizations"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "uv run lint-imports" in result.stdout
    assert "tests/modules/organizations/unit" in result.stdout
    _assert_names_no_other_unit(result.stdout, "organizations")


def test_make_test_docker_with_a_module_runs_only_that_modules_tests(tmp_path: Path) -> None:
    # `make test-docker unit=organizations` runs Organizations' unit and infrastructure
    # tests in the Docker test stack, and nothing of base's: not even the migrations,
    # which are one of base's whole-app suites. Under -n, make still runs the
    # $(MAKE) lines, so the two sub-makes print their commands too.
    _add_module_test_folders(tmp_path, "unit", "integration/with_infra")
    _add_shared_test_folders(tmp_path, "unit", "integration/with_infra")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker", "unit=organizations"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "tests/modules/organizations/unit" in result.stdout
    assert "tests/modules/organizations/integration/with_infra" in result.stdout
    _assert_names_no_other_unit(result.stdout, "organizations")


def test_make_test_docker_with_base_runs_bases_tests_and_the_whole_app_suites(tmp_path: Path) -> None:
    # `make test-docker unit=base` runs every one of base's folders, including the
    # whole-app suites (characterisation, sanity, smoke, migrations), and no module's
    # or shared's tests.
    _add_module_test_folders(tmp_path, "unit", "integration/with_infra")
    _add_shared_test_folders(tmp_path, "unit", "integration/with_infra")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker", "unit=base"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    for folder in (
        "tests/base/characterisation",
        "tests/base/sanity",
        "tests/base/unit",
        "tests/base/integration/no_infra",
        "tests/base/smoke",
        "tests/base/integration/with_infra",
        "tests/base/integration/migrations",
    ):
        assert folder in result.stdout
    _assert_names_no_other_unit(result.stdout, "base")


def test_make_test_docker_with_shared_runs_only_shareds_tests(tmp_path: Path) -> None:
    # `make test-docker unit=shared` runs shared's unit and infrastructure tests, and
    # nothing of base's or any module's.
    _add_module_test_folders(tmp_path, "unit", "integration/with_infra")
    _add_shared_test_folders(tmp_path, "unit", "integration/with_infra")
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker", "unit=shared"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "tests/shared/unit" in result.stdout
    assert "tests/shared/integration/with_infra" in result.stdout
    _assert_names_no_other_unit(result.stdout, "shared")


def test_an_unknown_unit_is_refused_naming_the_known_units(tmp_path: Path) -> None:
    # A misspelt unit would narrow every list to nothing, and pytest given no paths
    # falls back to pyproject.toml's testpaths: every test, the with_infra ones
    # included. So make refuses a name it doesn't know before running anything,
    # and lists the ones it does: base, shared and every folder under
    # tests/modules/. Python's __pycache__ folder and the package's __init__.py
    # sit there too, and neither is a module.
    _add_module_test_folders(tmp_path, "unit")
    _add_shared_test_folders(tmp_path, "unit")
    (tmp_path / "tests" / "modules" / "__pycache__").mkdir()
    (tmp_path / "tests" / "modules" / "__init__.py").touch()
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test", "unit=organisations"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unknown unit 'organisations'." in result.stderr
    assert "Known units: base notifications organizations shared" in result.stderr


def test_a_unit_with_no_tests_for_a_run_is_refused(tmp_path: Path) -> None:
    # A known unit can still have no tests for one kind of run: here a module with
    # only infrastructure tests, asked for its light tests. pytest given no paths
    # would fall back to pyproject.toml's testpaths and run every test, the
    # with_infra ones on the host included, so make stops and names the unit.
    (tmp_path / "tests" / "modules" / "billing" / "integration" / "with_infra").mkdir(parents=True)
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test", "unit=billing"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unit 'billing' has no tests for this run in tests/modules/billing/" in result.stderr


def test_a_unit_with_tests_only_for_another_run_still_runs_them(tmp_path: Path) -> None:
    # The same module's Docker run has tests to run, so it goes ahead: the check is
    # per run, not per unit. This passes before the check exists; it is there so
    # the check can't refuse more than it should.
    (tmp_path / "tests" / "modules" / "billing" / "integration" / "with_infra").mkdir(parents=True)
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker", "unit=billing"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    assert "tests/modules/billing/integration/with_infra" in result.stdout


def test_a_unit_with_no_tests_at_all_is_refused_in_docker(tmp_path: Path) -> None:
    # A module's test folder created before its first test gives the Docker run
    # nothing either, so test-docker-app stops the same way.
    (tmp_path / "tests" / "modules" / "draft").mkdir(parents=True)
    _copy_makefile(tmp_path)

    result = subprocess.run(
        ["/usr/bin/make", "-n", "test-docker", "unit=draft"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Unit 'draft' has no tests for this run in tests/modules/draft/" in result.stderr
