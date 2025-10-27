# app/services/odoo_rpc.py
import os
import json
import urllib.request

class OdooRPC:
    def __init__(self):
        self.url = os.environ["ODOO_URL"].rstrip("/")
        self.db = os.environ["ODOO_DB"]
        self.user = os.environ["ODOO_USER"]
        self.password = os.environ["ODOO_PASS"]
        self.uid = self._authenticate()

    def _jsonrpc(self, path: str, payload: dict):
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as f:
            return json.loads(f.read().decode())

    def _authenticate(self) -> int:
        res = self._jsonrpc("/jsonrpc", {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "common",
                "method": "authenticate",
                "args": [self.db, self.user, self.password, {}],
            },
            "id": 1,
        })
        uid = res.get("result")
        if not uid:
            raise RuntimeError("Falha na autenticação no Odoo")
        return uid

    def call_kw(self, model: str, method: str, args=None, kwargs=None):
        args = args or []
        kwargs = kwargs or {}
        res = self._jsonrpc("/jsonrpc", {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "service": "object",
                "method": "execute_kw",
                "args": [self.db, self.uid, self.password, model, method, args, kwargs],
            },
            "id": 2,
        })
        if "error" in res:
            raise RuntimeError(str(res["error"]))
        return res.get("result")
