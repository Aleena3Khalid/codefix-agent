import pytest

from cart import Cart, apply_discount, qualifies_for_free_shipping, subtotal


def test_subtotal():
    assert subtotal([{"price": 2.5, "qty": 2}, {"price": 1.0, "qty": 3}]) == 8.0


def test_apply_discount():
    assert apply_discount(200, 10) == 180


def test_apply_discount_zero():
    assert apply_discount(99.99, 0) == 99.99


def test_apply_discount_rejects_bad_percent():
    with pytest.raises(ValueError):
        apply_discount(100, 150)


def test_free_shipping_at_threshold():
    assert qualifies_for_free_shipping(50) is True


def test_no_free_shipping_below_threshold():
    assert qualifies_for_free_shipping(49.99) is False


def test_cart_merges_same_item():
    cart = Cart()
    cart.add("pen", 1.5)
    cart.add("pen", 1.5, qty=2)
    assert len(cart.items) == 1
    assert cart.total() == 4.5