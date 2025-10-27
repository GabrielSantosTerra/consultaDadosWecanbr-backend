# app/services/odooLivechat.py
from typing import Any, Dict, List, Optional
from app.services.odooHelpdesk import OdooHelpdeskService, OdooError

class OdooLivechatService:
    """
    Serviço de Live Chat que reaproveita a sessão/RPC do seu OdooHelpdeskService (httpx + ODOO_PASSWORD).
    """
    def __init__(self) -> None:
        try:
            self._svc = OdooHelpdeskService()
        except Exception as e:
            raise OdooError(f"OdooHelpdeskService: {e}")

    def _exec(self, model: str, method: str, args: Optional[List[Any]] = None, kwargs: Optional[Dict[str, Any]] = None) -> Any:
        # Reusa o _exec do seu serviço
        return self._svc._exec(model, method, args or [], kwargs or {})

    def list_channels(self, limit: int = 300) -> List[Dict[str, Any]]:
        # im_livechat.channel
        return self._exec(
            "im_livechat.channel",
            "search_read",
            [[], ["id", "name"]],
            {"limit": limit, "order": "name asc"},
        ) or []

    def find_channel_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        res = self._exec(
            "im_livechat.channel",
            "search_read",
            [[["name", "=", name]], ["id", "name"]],
            {"limit": 1},
        )
        return res[0] if res else None

    def get_helpdesk_team(self, team_id: int) -> Optional[Dict[str, Any]]:
        res = self._exec(
            "helpdesk.team",
            "search_read",
            [[["id", "=", int(team_id)]], ["id", "name", "company_id"]],
            {"limit": 1},
        )
        return res[0] if res else None
