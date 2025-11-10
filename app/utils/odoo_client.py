from typing import Any, Dict, List, Optional
import xmlrpc.client
from config.settings import settings


class OdooClient:
    """
    Cliente compatível com Odoo 15→18.
    - Odoo 17/18: canais = 'discuss.channel'; mensagens pertencem a um thread via (model, res_id).
    - Odoo <=16:   canais = 'mail.channel' (legado).
    """
    def __init__(self, url: str, db: str, user: str, password: str, timeout: int = 20):
        self.url = url.rstrip("/")
        self.db = db
        self.user = user
        self.password = password
        self.timeout = timeout

        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", allow_none=True)
        self._object = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object", allow_none=True)
        self.uid = self._common.authenticate(self.db, self.user, self.password, {})
        if not self.uid:
            raise RuntimeError("Falha ao autenticar no Odoo. Verifique ODOO_URL/DB/USER/PASSWORD.")

        # Detecta qual modelo de canal está disponível (v17/18 = discuss.channel; v<=16 = mail.channel)
        self._channel_model = "discuss.channel" if self.model_exists("discuss.channel") else "mail.channel"

    @classmethod
    def from_settings(cls) -> "OdooClient":
        return cls(
            url=settings.ODOO_URL,
            db=settings.ODOO_DB,
            user=settings.ODOO_USER,
            password=settings.ODOO_PASSWORD,
            timeout=getattr(settings, "ODOO_HTTP_TIMEOUT", 20),
        )

    # ----------------- Helpers base -----------------
    def version(self) -> Dict[str, Any]:
        return self._common.version()

    def execute_kw(
        self,
        model: str,
        method: str,
        args: Optional[List[Any]] = None,
        kwargs: Optional[Dict[str, Any]] = None,
    ) -> Any:
        args = args or []
        kwargs = kwargs or {}
        return self._object.execute_kw(self.db, self.uid, self.password, model, method, args, kwargs)

    def search_read(
        self,
        model: str,
        domain: List[Any],
        fields: Optional[List[str]] = None,
        limit: Optional[int] = None,
        order: Optional[str] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        if offset is not None:
            kwargs["offset"] = offset
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def read(self, model: str, ids: List[int], fields: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute_kw(model, "read", [ids], kwargs)

    def create(self, model: str, values: Dict[str, Any]) -> int:
        return self.execute_kw(model, "create", [values], {})

    def write(self, model: str, ids: List[int], values: Dict[str, Any]) -> bool:
        return self.execute_kw(model, "write", [ids, values], {})

    def model_exists(self, model_name: str) -> bool:
        """Retorna True se o modelo existir em ir.model."""
        try:
            res = self.search_read("ir.model", [["model", "=", model_name]], fields=["id"], limit=1)
            return bool(res)
        except Exception:
            return False

    # ----------------- Live Chat / Discuss -----------------
    def list_channels(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista canais (discuss.channel em v17/18; mail.channel em v<=16)."""
        model = self._channel_model
        fields = ["id", "name"]
        for extra in ("channel_type", "public"):
            try:
                self.search_read(model, [], fields=["id", extra], limit=1)
                fields.append(extra)
            except Exception:
                pass
        return self.search_read(model, [], fields=fields, limit=limit, order="id desc")

    def get_messages_by_channel(self, channel_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Lista mensagens do canal via (model,res_id)."""
        channel_model = self._channel_model
        domain = [["model", "=", channel_model], ["res_id", "=", channel_id]]
        fields = ["id", "date", "author_id", "body", "message_type", "model", "res_id"]
        return self.search_read("mail.message", domain, fields=fields, limit=limit, order="id asc")

    def get_messages_since_id(self, channel_id: int, after_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Lista mensagens do canal com id > after_id.
        Útil para 'ver as mensagens enviadas a partir do id X'.
        """
        channel_model = self._channel_model
        domain = [
            ["model", "=", channel_model],
            ["res_id", "=", channel_id],
            ["id", ">", after_id],
        ]
        fields = ["id", "date", "author_id", "body", "message_type", "model", "res_id"]
        return self.search_read("mail.message", domain, fields=fields, limit=limit, order="id asc")

    def get_message_by_id(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Lê uma única mail.message pelo ID."""
        rows = self.read(
            "mail.message",
            [message_id],
            fields=["id", "date", "author_id", "body", "message_type", "model", "res_id"],
        )
        return rows[0] if rows else None

    def get_messages_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        """Lê várias mail.message pelos IDs."""
        if not ids:
            return []
        return self.read(
            "mail.message",
            ids,
            fields=["id", "date", "author_id", "body", "message_type", "model", "res_id"],
        )

    def send_message_to_channel(self, channel_id: int, body: str) -> int:
        """Posta mensagem no canal detectado (discuss.channel/mail.channel)."""
        model = self._channel_model
        message_id = self.execute_kw(
            model,
            "message_post",
            args=[[channel_id]],
            kwargs={"body": body, "message_type": "comment", "subtype_xmlid": "mail.mt_comment"},
        )
        return int(message_id)

    # ----------------- Helpdesk (opcional) -----------------
    def create_helpdesk_ticket(self, name: str, description: str, team_id: Optional[int] = None) -> int:
        values = {"name": name, "description": description}
        if team_id:
            values["team_id"] = team_id
        return self.create("helpdesk.ticket", values)
