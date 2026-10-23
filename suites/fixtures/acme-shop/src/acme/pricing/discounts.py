"""acme/pricing/discounts.py (synthetic fixture)."""

# TODO: revisit edge case 1
# TODO: revisit edge case 2
# TODO: revisit edge case 3

def calculate_discount(total: float, code: str) -> float:
    return total * 0.1 if code == 'WELCOME10' else 0.0
