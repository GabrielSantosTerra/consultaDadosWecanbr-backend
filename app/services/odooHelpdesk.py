# app/services/odooHelpdesk.py
import os
import re
from typing import Any, Dict, List, Optional
import httpx

class OdooError(RuntimeError):
    pass

def _to_int_id(res: Any) -> int:
    """
    Converte o retorno de métodos como create()/message_post() para int.
    Aceita:
      - 123 / 123.0
      - "123" / " 123 "
      - [123] / ["123"]
      - "mail.message(123,)" ou "helpdesk.ticket(123,)" (recordset repr, com vírgula opcional)
    """
    # int/float direto
    if isinstance(res, (int, float)):
        try:
            return int(res)
        except Exception:
            pass

    # str: numérica ou recordset repr
    if isinstance(res, str):
        s = res.strip()
        if s.isdigit():
            return int(s)
        # lista como string, ex: "[123]"
        m = re.fullmatch(r"\[\s*(\d+)\s*\]", s)
        if m:
            return int(m.group(1))
        # recordset repr: model(123,) -> captura o número entre parênteses (vírgula opcional)
        m = re.search(r"\(\s*(\d+)\s*,?\s*\)", s)
        if m:
            return int(m.group(1))

    # lista python: pega o primeiro elemento se for int/str numérica
    if isinstance(res, list) and res:
        first = res[0]
        if isinstance(first, (int, float)) and str(int(first)) == str(first).split('.')[0]:
            return int(first)
        if isinstance(first, str) and first.strip().isdigit():
            return int(first.strip())

    raise OdooError(f"Resposta inesperada do Odoo (esperado int ou [int]): {res!r}")

class OdooHelpdeskService:
    def __init__(
        self,
        url: Optional[str] = None,
        db: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.url = (url or os.getenv("ODOO_URL", "")).rstrip("/")
        self.db = db or os.getenv("ODOO_DB", "")
        self.user = user or os.getenv("ODOO_USER", "")
        self.password = password or os.getenv("ODOO_PASSWORD", "")
        self.timeout = int(timeout or os.getenv("ODOO_HTTP_TIMEOUT", "20"))
        self._uid: Optional[int] = None
        if not all([self.url, self.db, self.user, self.password]):
            raise OdooError("Variáveis ODOO_URL/ODOO_DB/ODOO_USER/ODOO_PASSWORD ausentes.")

    # ---------- JSON-RPC ----------
    def _rpc(self, payload: Dict[str, Any]) -> Any:
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.url}/jsonrpc", json=payload)
            r.raise_for_status()
            data = r.json()
        if "error" in data:
            raise OdooError(str(data["error"]))
        return data.get("result")

    def _login(self) -> int:
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": "common", "method": "login", "args": [self.db, self.user, self.password]},
            "id": 1,
        }
        uid = self._rpc(payload)
        if not uid:
            raise OdooError("Falha no login do Odoo.")
        self._uid = int(uid)
        return self._uid

    def _exec(self, model: str, method: str, args: List[Any] | None = None, kwargs: Dict[str, Any] | None = None) -> Any:
        if self._uid is None:
            self._login()
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [self.db, self._uid, self.password, model, method, args or [], kwargs or {}],
            },
            "id": 2,
        }
        return self._rpc(payload)

    # ---------- HELPERS ----------
    def team_exists(self, team_id: int) -> bool:
        res = self._exec("helpdesk.team", "search_read", [[["id", "=", int(team_id)]]], {"fields": ["id"], "limit": 1})
        return bool(res)

    def _ensure_tags(self, names: List[str]) -> List[int]:
        tag_ids: List[int] = []
        for n in names or []:
            n = (n or "").strip()
            if not n:
                continue
            found = self._exec("helpdesk.tag", "search_read", [[["name", "=", n]]], {"fields": ["id"], "limit": 1})
            if found:
                tag_ids.append(int(found[0]["id"]))
            else:
                created = self._exec("helpdesk.tag", "create", [{"name": n}])  # normalmente retorna int
                tag_ids.append(_to_int_id(created))
        return tag_ids

    def create_partner_if_needed(self, name: Optional[str], email: Optional[str]) -> Optional[int]:
        if not name and not email:
            return None
        partner_id: Optional[int] = None
        if email:
            found = self._exec("res.partner", "search_read", [[["email", "=", email]]], {"fields": ["id"], "limit": 1})
            if found:
                partner_id = int(found[0]["id"])
        if not partner_id:
            created = self._exec("res.partner", "create", [{"name": name or (email or "Cliente"), "email": email}])
            partner_id = _to_int_id(created)
        return partner_id

    # ---------- HELP DESK ----------
    def list_teams(self, limit: int = 200) -> List[Dict[str, Any]]:
        return self._exec("helpdesk.team", "search_read", [[], ["id", "name"]], {"limit": limit, "order": "name asc"})

    def create_ticket(
        self,
        name: str,
        description_html: str = "",
        team_id: Optional[int] = None,
        partner_name: Optional[str] = None,
        partner_email: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        vals: Dict[str, Any] = {"name": name, "description": description_html}
        if team_id:
            if not self.team_exists(int(team_id)):
                raise OdooError(f"Helpdesk Team {team_id} não encontrado ou sem acesso.")
            vals["team_id"] = int(team_id)

        partner_id = self.create_partner_if_needed(partner_name, partner_email)
        if partner_id:
            vals["partner_id"] = partner_id

        # create: usar dict → retorno esperado: int (mas aceitamos [int])
        created = self._exec("helpdesk.ticket", "create", [vals])
        ticket_id = _to_int_id(created)

        # se houver tags válidas, relaciona
        if tags:
            tag_ids = self._ensure_tags(tags)
            if tag_ids:
                self._exec(
                    "helpdesk.ticket",
                    "write",
                    args=[[ticket_id], {"tag_ids": [(6, 0, tag_ids)]}],
                )

        return ticket_id

    def message_post(self, ticket_id: int, body_html: str, message_type: str = "comment") -> int:
        # Odoo 18 → args [[ticket_id]], kwargs com body/message_type
        res = self._exec(
            "helpdesk.ticket",
            "message_post",
            args=[[int(ticket_id)]],
            kwargs={"body": body_html, "message_type": message_type},
        )
        return _to_int_id(res)
