"""Unit tests for compute_effective_prices(), the port of Workerman's market
`prices` getter. CLAUDE.md documents the invariant this locks down: custom >
api > vendor, then tax (skipped for Keep items and vendor items), then
crafted items valued from components.
"""
from app import compute_effective_prices


def test_precedence_custom_beats_api_beats_vendor():
    result = compute_effective_prices(
        api_prices={"1": 100, "2": 200},
        vendor_prices={"1": 50},
        calculated_prices={},
        tax=1.0,
        custom_prices={"1": 999},
    )
    assert result["1"] == 999   # custom overrides both api and vendor
    assert result["2"] == 200   # only api has "2"


def test_api_beats_vendor_when_no_custom():
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={"1": 50},
        calculated_prices={},
        tax=1.0,
    )
    assert result["1"] == 100


def test_vendor_used_when_nothing_else_has_it():
    result = compute_effective_prices(
        api_prices={},
        vendor_prices={"1": 50},
        calculated_prices={},
        tax=1.0,
    )
    assert result["1"] == 50


def test_tax_applied_to_ordinary_items():
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={},
        calculated_prices={},
        tax=0.65,
    )
    assert result["1"] == 65.0


def test_tax_skipped_for_keep_items():
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={},
        calculated_prices={},
        tax=0.65,
        keep_items={"1": True},
    )
    assert result["1"] == 100


def test_tax_skipped_for_vendor_items_even_if_price_came_from_elsewhere():
    # "1" is a vendor item (a key in vendor_prices), but a custom override
    # outbids vendor's own value in the precedence chain. It should still be
    # tax-exempt: the exemption check is "is this id a vendor item", not
    # "did the final price come from vendor".
    result = compute_effective_prices(
        api_prices={},
        vendor_prices={"1": 50},
        calculated_prices={},
        tax=0.65,
        custom_prices={"1": 1000},
    )
    assert result["1"] == 1000  # untaxed despite tax=0.65


def test_crafted_price_from_components_uses_post_tax_component_prices():
    # component "1" is 100 pre-tax -> 65 post-tax (tax=0.65). Crafted item
    # "9999" needs 2x component "1"; the crafted-price loop runs after tax.
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={},
        calculated_prices={"9999": {"1": 2}},
        tax=0.65,
    )
    assert result["1"] == 65.0
    assert result["9999"] == 130.0


def test_crafted_price_missing_component_valued_at_zero():
    # Component "1" has no price anywhere - an unpriced component must not
    # crash the computation, it contributes 0 (matches the documented
    # "unpriced items are valued at 0" behavior, not a poisoned/NaN result).
    result = compute_effective_prices(
        api_prices={},
        vendor_prices={},
        calculated_prices={"9999": {"1": 2}},
        tax=0.65,
    )
    assert result["9999"] == 0


def test_custom_price_on_crafted_item_bypasses_component_computation():
    # The custom price wins over the components computation (the crafted-item
    # loop's `continue` skips re-deriving it), but a custom price is still an
    # ordinary price as far as tax is concerned - it isn't exempt just for
    # being custom, only `keep_items`/vendor items are. So it comes out taxed,
    # not as the raw value entered.
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={},
        calculated_prices={"9999": {"1": 2}},
        tax=0.65,
        custom_prices={"9999": 55555},
    )
    assert result["9999"] == 55555 * 0.65


def test_custom_price_untaxed_only_when_also_kept():
    result = compute_effective_prices(
        api_prices={},
        vendor_prices={},
        calculated_prices={},
        tax=0.65,
        custom_prices={"1": 55555},
        keep_items={"1": True},
    )
    assert result["1"] == 55555


def test_empty_string_custom_price_is_treated_as_unset():
    result = compute_effective_prices(
        api_prices={"1": 100},
        vendor_prices={},
        calculated_prices={},
        tax=1.0,
        custom_prices={"1": ""},
    )
    assert result["1"] == 100
