from __future__ import annotations


def test_the_root_help_lists_every_command_in_a_section(capsys):
    from ov.cli.commands import BUILTIN_NAMES
    from ov.cli.help import SECTIONS
    from ov.cli.main import build_parser

    listed = {name for _, names in SECTIONS for name in names}
    assert BUILTIN_NAMES - {"ui"} <= listed

    build_parser([]).print_help()
    shown = capsys.readouterr().out
    assert "Usage  ov [-i INSTANCE] <command> [options]" in shown
    for name in listed:
        assert f"  {name} " in shown
