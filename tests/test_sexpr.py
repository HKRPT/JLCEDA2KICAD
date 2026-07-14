from jlceda2kicad.sexpr import (
    SExprError,
    find_symbol_spans_by_property,
    parse_one,
    remove_spans,
    rewrite_footprint_models,
)


def test_parse_one_handles_parentheses_and_escaped_quotes_in_strings() -> None:
    text = '(root (value "a (quoted) \\"value\\"") (child 1))'

    root = parse_one(text)

    assert root.head == "root"
    assert root.end == len(text)


def test_parse_one_rejects_unbalanced_input() -> None:
    try:
        parse_one('(root (value "broken")')
    except SExprError as error:
        assert "括号" in str(error)
    else:
        raise AssertionError("unbalanced input was accepted")


def test_find_symbol_spans_matches_only_direct_symbol_with_lcsc_property() -> None:
    text = """(kicad_symbol_lib
  (version 20231120)
  (symbol "KEEP" (property "LCSC Part" "C1"))
  (symbol "REMOVE" (property "LCSC Part" "C2040") (symbol "nested"))
)"""

    spans = find_symbol_spans_by_property(text, "LCSC Part", "C2040")
    updated = remove_spans(text, spans)

    assert len(spans) == 1
    assert 'symbol "KEEP"' in updated
    assert 'symbol "REMOVE"' not in updated


def test_rewrite_footprint_models_selects_step_or_removes_models() -> None:
    text = """(footprint "demo"
  (model "${KIPRJMOD}/libs/lcsc_project.3dshapes/demo.wrl"
    (offset (xyz 0 0 0)))
  (fp_line (start 0 0) (end 1 1))
)"""

    step = rewrite_footprint_models(text, "step")
    none = rewrite_footprint_models(text, "none")

    assert "demo.step" in step and "demo.wrl" not in step
    assert "(model" not in none
    assert "(fp_line" in none
