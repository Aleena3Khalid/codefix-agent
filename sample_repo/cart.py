"""Shopping cart helpers."""


def subtotal(items):
    """Sum price * qty for a list of {"price": float, "qty": int} items."""
    return round(sum(item["price"] * item["qty"] for item in items), 2)


def apply_discount(total, percent):
    """Return the total after a percentage discount. percent must be between 0 and 100."""
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")
    return round(total * percent / 100, 2)


def qualifies_for_free_shipping(total, threshold=50):
    """Orders of at least `threshold` ship for free."""
    return total > threshold


class Cart:
    def __init__(self):
        self.items = []

    def add(self, name, price, qty=1):
        """Add an item. Adding the same name again increases its quantity."""
        for item in self.items:
            if item["name"] == name:
                item["qty"] += qty
                return
        self.items.append({"name": name, "price": price, "qty": qty})

    def total(self, discount_percent=0):
        return apply_discount(subtotal(self.items), discount_percent) if discount_percent else subtotal(self.items)