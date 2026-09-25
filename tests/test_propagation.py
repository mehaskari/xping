"""DNS propagation across public resolvers."""

from unittest.mock import patch

from xping.cli.verdict import evaluate
from xping.diagnostics import lookup as lookup_diag
from xping.diagnostics import propagation as prop_diag
from xping.exporters import export_csv
from xping.models.propagation import PropagationResult, ResolverAnswer


def _answer(name, records, status="NOERROR"):
    return ResolverAnswer(name, "9.9.9.9", status, records, 10.0)


def test_consistency_majority_and_matches():
    r = PropagationResult(
        name="h",
        rtype="A",
        answers=[
            _answer("a", ["1.1.1.1"]),
            _answer("b", ["1.1.1.1"]),
            _answer("c", ["2.2.2.2"]),
            _answer("d", [], "TIMEOUT"),
        ],
    )
    assert not r.consistent and r.distinct_answers == 2 and r.majority == ["1.1.1.1"]
    assert r.problems() == []  # disagreement alone is not a failure
    r.expected = ["1.1.1.1"]
    assert r.matching == 2 and r.matches(r.answers[2]) is False
    assert r.problems() == [("1 of 3 resolvers do not return 1.1.1.1", True)]


def test_nobody_answered_and_nxdomain():
    silent = PropagationResult(name="h", rtype="A", answers=[_answer("a", [], "SERVFAIL")])
    assert silent.problems() and evaluate(silent)
    gone = PropagationResult(name="h", rtype="A", answers=[_answer("a", [], "NXDOMAIN")])
    assert gone.problems() == [] and gone.consistent


def test_propagation_queries_every_resolver():
    calls = []

    def fake_query(name, rtype, server=None):
        calls.append(server)
        return "NOERROR", ["93.184.216.34"], 5.0

    with patch.object(prop_diag, "query", side_effect=fake_query):
        result = prop_diag.propagation(
            "example.com.", expected=["93.184.216.34"], servers=["10.0.0.53"], quiet=True
        )
    assert result.name == "example.com" and result.consistent
    assert None in calls and "10.0.0.53" in calls and "8.8.8.8" in calls
    assert len(result.answers) == len(prop_diag.PUBLIC_RESOLVERS) + 2
    assert evaluate(result) == []


def test_system_resolver_raw_fallback_without_dig():
    def fake_query(name, rtype, server=None):
        return ("ERROR", [], 0.0) if server is None else ("NOERROR", ["1.2.3.4"], 3.0)

    with (
        patch.object(prop_diag, "query", side_effect=fake_query),
        patch.object(prop_diag, "_system_server", return_value="192.168.1.1"),
    ):
        answer = prop_diag._ask("System", None, "h", "A")
    assert answer.server == "192.168.1.1" and answer.records == ["1.2.3.4"]


def test_query_normalizes_dig_answers():
    mx = "github.com.\t3600\tIN\tMX\t0 GitHub-com.mail.protection.outlook.com.\n"
    with patch.object(lookup_diag, "_dig_query", return_value=("NOERROR", mx)):
        status, records, _ms = lookup_diag.query("github.com", "mx")
    assert status == "NOERROR" and records == ["0 github-com.mail.protection.outlook.com"]


def test_csv_and_cli(capsys):
    from xping.cli import commands
    from xping.cli.parser import build_parser

    r = PropagationResult(name="h", rtype="A", expected=["1.1.1.1"], answers=[_answer("a", ["1.1.1.1"])])
    rows = export_csv(r).splitlines()
    assert rows[0].endswith(",matches") and rows[1].endswith(",True")
    args = build_parser().parse_args(["propagation", "h", "-t", "mx", "--expect", "10 mx.h", "--json"])
    assert args.rtype == "MX" and args.expect == ["10 mx.h"]
    with patch("xping.cli.commands.propagation", return_value=r) as fake:
        commands.cmd_propagation(args)
    assert fake.call_args.kwargs["rtype"] == "MX"
    assert '"consistent": true' in capsys.readouterr().out
