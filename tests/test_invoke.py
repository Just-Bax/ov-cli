from __future__ import annotations

import json

import pytest
from conftest import OPENAPI

from ov.errors import OvError
from ov.invoke import build_plan, dest_name, flag_name
from ov.spec import Param, parse


@pytest.fixture
def spec():
    return parse(OPENAPI, "v3")


def test_path_parameter_is_substituted(spec):
    operation = spec.find("users:get-user-by-id")
    plan = build_plan(operation, {dest_name(operation.path_params[0]): 42})
    assert plan.path == "/v3/users/42"


def test_path_parameter_is_escaped(spec):
    operation = spec.find("trackor-types:search")
    plan = build_plan(operation, {}, path_values=["trackor_type=A/B C"])
    assert plan.path == "/v3/trackor_types/A%2FB%20C/trackors/search"


def test_missing_path_parameter_is_refused(spec):
    operation = spec.find("users:get-user-by-id")
    with pytest.raises(OvError, match="Missing path parameter"):
        build_plan(operation, {})


def test_query_parameters_come_from_flags_and_from_q(spec):
    operation = spec.find("users:get-user-by-un-or-email")
    values = {dest_name(p): "jsmith" for p in operation.params if p.name == "user_name"}
    plan = build_plan(operation, values, query=["email=j@acme.com"])
    assert ("user_name", "jsmith") in plan.params
    assert ("email", "j@acme.com") in plan.params


def test_array_parameter_repeats(spec):
    operation = spec.find("trackor-types:search")
    fields = next(p for p in operation.params if p.name == "fields")
    plan = build_plan(
        operation,
        {dest_name(fields): ["TRACKOR_KEY", "STATUS"]},
        path_values=["trackor_type=CONTRACT"],
    )
    assert plan.params.count(("fields", "TRACKOR_KEY")) == 1
    assert plan.params.count(("fields", "STATUS")) == 1


def test_a_parameter_named_like_a_cli_flag_gets_no_flag():
    assert flag_name(Param(name="json", location="query")) is None
    assert flag_name(Param(name="user_name", location="query")) == "user-name"


def test_a_parameter_named_like_a_cli_flag_is_still_reachable(spec):
    """'json' collides with --json, so -q has to remain a complete escape hatch."""
    operation = spec.find("trackor-types:search")
    plan = build_plan(operation, {}, path_values=["trackor_type=X"], query=["json=true"])
    assert ("json", "true") in plan.params


def test_data_accepts_inline_json(spec):
    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, data='{"user_name": "jsmith"}')
    assert plan.json_body == {"user_name": "jsmith"}


def test_data_accepts_a_file(spec, tmp_path):
    path = tmp_path / "user.json"
    path.write_text(json.dumps({"user_name": "jsmith"}), encoding="utf-8")

    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, data=f"@{path}")
    assert plan.json_body == {"user_name": "jsmith"}


def test_fields_build_a_body(spec):
    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, fields=["user_name=jsmith", "email=j@acme.com"])
    assert plan.json_body == {"user_name": "jsmith", "email": "j@acme.com"}


def test_a_typed_field_is_parsed_as_json(spec):
    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, fields=["user_name=jsmith", 'roles:=["ADMIN"]'])
    assert plan.json_body["roles"] == ["ADMIN"]


def test_a_dotted_field_nests(spec):
    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, fields=["fields.STATUS=Open", "fields.OWNER=jsmith"])
    assert plan.json_body == {"fields": {"STATUS": "Open", "OWNER": "jsmith"}}


def test_a_required_body_is_enforced(spec):
    operation = spec.find("users:create-user")
    with pytest.raises(OvError, match="requires a request body"):
        build_plan(operation, {})


def test_data_and_field_are_not_combined(spec):
    operation = spec.find("users:create-user")
    with pytest.raises(OvError, match="use one of them"):
        build_plan(operation, {}, data="{}", fields=["a=b"])


def test_headers_are_parsed_on_colons(spec):
    operation = spec.find("schema:get-trackor-types")
    plan = build_plan(operation, {}, headers=["X-Trace: 7"])
    assert plan.headers == {"X-Trace": "7"}


def test_a_malformed_pair_is_reported(spec):
    operation = spec.find("schema:get-trackor-types")
    with pytest.raises(OvError, match="NAME=VALUE"):
        build_plan(operation, {}, query=["broken"])


def test_a_file_upload_becomes_multipart(spec, tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes(b"a,b\n1,2\n")

    operation = spec.find("users:create-user")
    plan = build_plan(operation, {}, files=[f"file=@{path}"])
    assert plan.files["file"][0] == "data.csv"
