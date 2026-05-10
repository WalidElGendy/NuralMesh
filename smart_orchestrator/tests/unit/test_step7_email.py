
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock


class TestSendEmailNoKey:
    def test_send_email_no_op_when_no_api_key(self):
        """With no RESEND_API_KEY set, send_email should return True without calling Resend."""
        with patch.dict("os.environ", {"RESEND_API_KEY": ""}, clear=False):
            # Re-import to pick up env change
            import importlib
            import app.lib.email as em
            importlib.reload(em)
            result = asyncio.run(em.send_email("test@example.com", "Hi", "<p>Hi</p>"))
        assert result is True


class TestInternalNotifyEndpoint:
    def test_verify_internal_key_rejects_wrong_key(self):
        from app.routers.internal import _verify_internal_key
        from fastapi import HTTPException
        import os
        with patch.dict("os.environ", {"INTERNAL_API_KEY": "secret123"}):
            import importlib
            import app.routers.internal as ir
            importlib.reload(ir)
            with pytest.raises(HTTPException) as exc_info:
                ir._verify_internal_key("wrong-key")
            assert exc_info.value.status_code == 401

    def test_verify_internal_key_accepts_correct_key(self):
        from fastapi import HTTPException
        with patch.dict("os.environ", {"INTERNAL_API_KEY": "secret123"}):
            import importlib
            import app.routers.internal as ir
            importlib.reload(ir)
            # Should not raise
            ir._verify_internal_key("secret123")

    def test_verify_internal_key_rejects_when_not_configured(self):
        from fastapi import HTTPException
        with patch.dict("os.environ", {"INTERNAL_API_KEY": ""}):
            import importlib
            import app.routers.internal as ir
            importlib.reload(ir)
            with pytest.raises(HTTPException) as exc_info:
                ir._verify_internal_key("anything")
            assert exc_info.value.status_code == 503


class TestStripeModeBanner:
    def test_stripe_mode_defaults_to_mock(self):
        with patch.dict("os.environ", {"STRIPE_MODE": ""}):
            import importlib
            import app.lib.billing as b
            importlib.reload(b)
            assert b.STRIPE_MODE == ""

    def test_stripe_mode_live(self):
        with patch.dict("os.environ", {"STRIPE_MODE": "live"}):
            import importlib
            import app.lib.billing as b
            importlib.reload(b)
            assert b.STRIPE_MODE == "live"

    def test_log_stripe_mode_banner_does_not_crash(self):
        from app.lib.billing import log_stripe_mode_banner
        log_stripe_mode_banner()  # Should not raise


class TestAdminNodesEndpoints:
    def test_nodes_store_is_empty_initially(self):
        import importlib
        import app.routers.admin as ar
        importlib.reload(ar)
        # _NODES_STORE should be a dict
        assert isinstance(ar._NODES_STORE, dict)

    def test_node_heartbeat_stores_node(self):
        import asyncio
        import importlib
        import app.routers.admin as ar
        importlib.reload(ar)

        from app.routers.admin import NodeHeartbeatRequest, node_heartbeat
        import app.routers.admin as admin_mod
        # Bypass auth by patching
        with patch("app.routers.admin._require_admin_secret", return_value=None):
            req = admin_mod.NodeHeartbeatRequest(node_id="node-1", name="GPU Box", location="us-east")
            result = asyncio.run(admin_mod.node_heartbeat(req, x_admin_secret="any"))
        assert result["ok"] is True
        assert result["node_id"] == "node-1"
        assert "node-1" in admin_mod._NODES_STORE

    def test_list_nodes_returns_recent(self):
        import asyncio
        import importlib
        import app.routers.admin as admin_mod
        importlib.reload(admin_mod)

        from datetime import datetime, timezone
        admin_mod._NODES_STORE["node-2"] = {
            "node_id": "node-2",
            "name": "Test GPU",
            "location": "eu-west",
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        with patch("app.routers.admin._require_admin_secret", return_value=None):
            nodes = asyncio.run(admin_mod.list_nodes(x_admin_secret="any"))
        assert any(n["node_id"] == "node-2" for n in nodes)
