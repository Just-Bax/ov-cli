from __future__ import annotations


def test_a_bare_case_number_or_link_is_a_case():
    from ov.agent.engine.cases import case_ref

    assert case_ref("193915") == "193915"
    assert case_ref(" Case #193915 ") == "193915"
    link = "https://trackor.onevizion.com/form/ConfigAppForm.do?id=100124829949"
    assert case_ref(link) == link
    assert case_ref("why does case 193915 fail?") is None
