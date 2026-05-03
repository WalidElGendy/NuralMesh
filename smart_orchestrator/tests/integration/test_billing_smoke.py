
"""
Integration smoke test for Stripe billing.
Runs against Stripe test-mode when STRIPE_MODE=test and STRIPE_SECRET_KEY is set.
Skipped in CI if no STRIPE_SECRET_KEY is set.
"""
import os
import pytest

STRIPE_MODE = os.getenv("STRIPE_MODE", "mock")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")

skip_unless_test_mode = pytest.mark.skipif(
    STRIPE_MODE != "test" or not STRIPE_SECRET_KEY,
    reason="Requires STRIPE_MODE=test and STRIPE_SECRET_KEY set"
)

@skip_unless_test_mode
def test_checkout_session_creates_redirect_url():
    """Creates a Stripe test checkout session and verifies redirect URL is returned."""
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "NeuralMesh Pro"},
                "unit_amount": 2900,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        mode="subscription",
        success_url="https://neuralmesh.ai/success",
        cancel_url="https://neuralmesh.ai/cancel",
    )
    assert session.url, "Checkout session should have a URL"
    assert "checkout.stripe.com" in session.url, f"Expected stripe URL, got: {session.url}"

@skip_unless_test_mode
def test_checkout_session_mode_is_subscription():
    import stripe
    stripe.api_key = STRIPE_SECRET_KEY
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": "Test Plan"},
                "unit_amount": 100,
                "recurring": {"interval": "month"},
            },
            "quantity": 1,
        }],
        mode="subscription",
        success_url="https://neuralmesh.ai/ok",
        cancel_url="https://neuralmesh.ai/cancel",
    )
    assert session.mode == "subscription"
