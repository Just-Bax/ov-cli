from __future__ import annotations

import pytest
from conftest import OPENAPI, signature

from ov.errors import Ambiguous, NotFound
from ov.spec import kebab, operation_name, parse


@pytest.fixture
def spec():
    return parse(OPENAPI, "v3")


def test_java_signature_reduces_to_the_method_name():
    assert operation_name(signature("getUserById"), "get", "/v3/users/{user_id}") == (
        "get-user-by-id"
    )


def test_plain_operation_id_is_kept():
    assert operation_name("createUser", "post", "/v3/users") == "create-user"


def test_missing_operation_id_falls_back_to_verb_and_path():
    assert operation_name("", "get", "/v3/schema/trackor_types") == "get-schema-trackor-types"


def test_kebab_handles_snake_and_camel():
    assert kebab("user_id") == "user-id"
    assert kebab("getUserByUnOrEmail") == "get-user-by-un-or-email"
    assert kebab("HTTPServer") == "http-server"


def test_every_operation_is_parsed(spec):
    assert len(spec.operations) == 6
    assert spec.tags == ["schema", "trackor-types", "users"]


def test_two_verbs_on_one_path_stay_distinct(spec):
    names = {o.name for o in spec.by_tag("users")}
    assert {"get-user-by-id", "delete-user", "get-user-by-un-or-email", "create-user"} == names


def test_path_parameters_are_required(spec):
    operation = spec.find("users:get-user-by-id")
    assert [p.name for p in operation.path_params] == ["user_id"]
    assert operation.path_params[0].required


def test_undeclared_path_parameter_is_recovered(spec):
    """DELETE /v3/users/{user_id} declares no parameters at all."""
    operation = spec.find("users:delete-user")
    assert [p.name for p in operation.path_params] == ["user_id"]


def test_request_body_ref_is_resolved(spec):
    operation = spec.find("users:create-user")
    assert operation.body is not None
    assert operation.body.required
    assert operation.body.schema["properties"]["user_name"]["type"] == "string"


def test_array_and_enum_parameters_keep_their_shape(spec):
    operation = spec.find("trackor-types:search")
    by_name = {p.name: p for p in operation.params}
    assert by_name["fields"].type == "array[string]"
    assert by_name["order"].enum == ["asc", "desc"]


def test_find_accepts_method_and_path(spec):
    assert spec.find("GET /v3/users").name == "get-user-by-un-or-email"


def test_find_reports_ambiguity(spec):
    with pytest.raises(Ambiguous) as caught:
        spec.find("user")
    assert "matches" in str(caught.value)


def test_find_reports_a_miss(spec):
    with pytest.raises(NotFound):
        spec.find("no-such-thing")


def test_search_covers_path_and_summary(spec):
    assert spec.search("trackor_types")
    assert spec.search("Read Trackor Types")
