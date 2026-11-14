"""
Characterisation test for the CLI's command tree (docs/plans/16-modular-monolith.md,
Step 0). It records every group and command `python -m app.base.main.cli` offers today, in
the order `--help` lists them, with each one's option flags: what people and scripts
(cron jobs, seeding) actually type. The tree is assembled by hand in
src/app/base/main/cli/root_group.py and src/app/base/main/cli/users/group.py, which the
restructuring moves. It is not a RED/GREEN cycle: it pins existing behaviour and passes
on its first run (O2: strict).

Defaults, types and help texts are left out: they live in the command files themselves,
which a pure move can't change.
"""

import click

from app.base.main.cli.root_group import root_group

# (the command as typed, its option flags in order). "cli" stands for
# `python -m app.base.main.cli`, whose import path Step 2 changes; the commands must not.
TODAYS_COMMAND_TREE: list[tuple[str, list[list[str]]]] = [
    ("cli", [["--username", "-u"], ["--password", "-p"]]),
    ("cli users", []),
    ("cli users list", [["--limit"], ["--offset"], ["--sort-by"], ["--order"]]),
    ("cli users create-user", [["--username"], ["--email"], ["--phone-number"], ["--password"], ["--role"]]),
    ("cli users set-user-password", [["--user-id"], ["--password"]]),
    ("cli users grant-admin", [["--user-id"]]),
    ("cli users revoke-admin", [["--user-id"]]),
    ("cli users activate-user", [["--user-id"]]),
    ("cli users deactivate-user", [["--user-id"]]),
]


def _command_tree(command: click.Command, path: str) -> list[tuple[str, list[list[str]]]]:
    # Walks the tree depth-first in the order the commands were added, which is the
    # order --help lists them. Only reads click's own description of each command:
    # nothing is invoked, so there is no prompt, no container and no database.
    options = [param.opts for param in command.params if isinstance(param, click.Option)]
    entries = [(path, options)]
    if isinstance(command, click.Group):
        for name, subcommand in command.commands.items():
            entries.extend(_command_tree(subcommand, f"{path} {name}"))
    return entries


def test_the_cli_offers_exactly_todays_commands_and_options() -> None:
    assert _command_tree(root_group, "cli") == TODAYS_COMMAND_TREE
