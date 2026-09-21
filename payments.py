import json
import urllib.error
import urllib.request


class PaymentGatewayError(RuntimeError):
    pass


class PaystackGateway:
    """Small Paystack adapter. It stays disabled until PAYSTACK_SECRET_KEY is configured."""

    base_url = "https://api.paystack.co"

    def __init__(self, secret_key, callback_url=""):
        self.secret_key = secret_key
        self.callback_url = callback_url

    @property
    def enabled(self):
        return bool(self.secret_key)

    def _request(self, path, payload=None):
        if not self.enabled:
            raise PaymentGatewayError("Payment gateway is not configured")
        body = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Authorization": f"Bearer {self.secret_key}",
                "Content-Type": "application/json",
            },
            method="POST" if payload is not None else "GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                result = json.loads(response.read().decode())
        except (urllib.error.URLError, ValueError) as exc:
            raise PaymentGatewayError("Payment gateway request failed") from exc
        if not result.get("status"):
            raise PaymentGatewayError(result.get("message", "Payment gateway rejected the request"))
        return result.get("data", {})

    def initialize(self, email, amount_kobo, reference):
        payload = {"email": email, "amount": amount_kobo, "reference": reference}
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        return self._request("/transaction/initialize", payload)

    def verify(self, reference):
        return self._request(f"/transaction/verify/{reference}")
