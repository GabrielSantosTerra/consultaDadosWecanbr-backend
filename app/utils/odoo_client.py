from typing import Any, Dict, List, Optional
import xmlrpc.client
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from config.settings import settings


IM_STATUS_ALLOWED = {
    "online",
    "offline",
    "away",
    "leave_online",
    "leave_offline",
}


class OdooClient:
    """
    Cliente compatível com Odoo 15→18.
    - Odoo 17/18: canais = 'discuss.channel'; mensagens pertencem a um thread via (model, res_id).
    - Odoo <=16:   canais = 'mail.channel' (legado).
    """

    def _init_(self, url: str, db: str, user: str, password: str, timeout: int = 20):
        self.url = url.rstrip("/")
        self.db = db
        self.user = user
        self.password = password
        self.timeout = timeout

        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True
        )
        self._object = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )

        self.uid = self._common.authenticate(self.db, self.user, self.password, {})
        if not self.uid:
            raise RuntimeError(
                "Falha ao autenticar no Odoo. Verifique ODOO_URL/DB/USER/PASSWORD."
            )

        self._channel_model = (
            "discuss.channel" if self.model_exists("discuss.channel") else "mail.channel"
        )

    @classmethod
    def from_settings(cls) -> "OdooClient":
        return cls(
            url=settings.ODOO_URL,
            db=settings.ODOO_DB,
            user=settings.ODOO_USER,
            password=settings.ODOO_PASSWORD,
            timeout=getattr(settings, "ODOO_HTTP_TIMEOUT", 20),
        )

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
        return self._object.execute_kw(
            self.db, self.uid, self.password, model, method, args, kwargs
        )

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
        if limit is not None:
            kwargs["limit"] = limit
        if order is not None:
            kwargs["order"] = order
        if offset is not None:
            kwargs["offset"] = offset
        return self.execute_kw(model, "search_read", [domain], kwargs)

    def read(
        self, model: str, ids: List[int], fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        kwargs: Dict[str, Any] = {}
        if fields:
            kwargs["fields"] = fields
        return self.execute_kw(model, "read", [ids], kwargs)

    def create(self, model: str, values: Dict[str, Any]) -> int:
        return self.execute_kw(model, "create", [values], {})

    def write(self, model: str, ids: List[int], values: Dict[str, Any]) -> bool:
        return self.execute_kw(model, "write", [ids, values], {})

    def model_exists(self, model_name: str) -> bool:
        try:
            res = self.search_read(
                "ir.model", [["model", "=", model_name]], fields=["id"], limit=1
            )
            return bool(res)
        except Exception:
            return False

    def set_im_status_for_user(self, user_id: int, status: str) -> bool:
        status = status.strip()
        if status not in IM_STATUS_ALLOWED:
            raise ValueError(f"Status inválido para im_status: {status!r}")
        return bool(self.write("res.users", [user_id], {"im_status": status}))

    def set_current_user_online(self) -> bool:
        return self.set_im_status_for_user(self.uid, "online")

    def set_current_user_offline(self) -> bool:
        return self.set_im_status_for_user(self.uid, "offline")

    def _helpdesk_candidate_channel_fields(self) -> List[str]:
        channel_model = self._channel_model
        rel_fields = self.search_read(
            "ir.model.fields",
            [
                ["model", "=", "helpdesk.ticket"],
                ["relation", "=", channel_model],
            ],
            fields=["name"],
            limit=0,
        )
        dynamic_field_names = [f["name"] for f in rel_fields if f.get("name")]

        classic_fields = ["x_zion_channel_id", "livechat_channel_id", "channel_id"]

        candidate_fields: List[str] = []
        for f in dynamic_field_names + classic_fields:
            if f not in candidate_fields:
                candidate_fields.append(f)

        return candidate_fields

    def find_ticket_id_by_channel(self, channel_id: int) -> Optional[int]:
        candidate_fields = self._helpdesk_candidate_channel_fields()

        for field_name in candidate_fields:
            try:
                rows = self.search_read(
                    "helpdesk.ticket",
                    [[field_name, "in", [channel_id]]],
                    fields=["id", field_name],
                    limit=1,
                    order="id desc",
                )
            except Exception:
                continue

            if rows and isinstance(rows[0].get("id"), int):
                return int(rows[0]["id"])

        return None

    # -------------------------------------------------
    # Attachments em mensagens + fallback por canal
    # -------------------------------------------------
    def _enrich_messages_with_attachments(
        self, msgs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not msgs:
            return msgs

        base_url = self.url.rstrip("/")

        all_attachment_ids: set[int] = set()
        for m in msgs:
            raw_ids = m.get("attachment_ids") or []
            if isinstance(raw_ids, list):
                for aid in raw_ids:
                    if isinstance(aid, int):
                        all_attachment_ids.add(aid)

        attachments_by_id: Dict[int, Dict[str, Any]] = {}

        if all_attachment_ids:
            try:
                atts = self.search_read(
                    "ir.attachment",
                    [["id", "in", list(all_attachment_ids)]],
                    fields=["id", "name", "mimetype", "res_model", "res_id"],
                    limit=0,
                )
            except Exception:
                atts = []

            for a in atts:
                aid = a.get("id")
                if isinstance(aid, int):
                    attachments_by_id[aid] = a

        for m in msgs:
            enriched_atts: List[Dict[str, Any]] = []
            raw_ids = m.get("attachment_ids") or []
            if isinstance(raw_ids, list):
                for aid in raw_ids:
                    if not isinstance(aid, int):
                        continue
                    a = attachments_by_id.get(aid)
                    if not a:
                        continue
                    name = a.get("name") or f"attachment-{aid}"
                    mimetype = a.get("mimetype")
                    url = f"{base_url}/web/image/{aid}/{quote(str(name))}"
                    enriched_atts.append(
                        {
                            "id": aid,
                            "name": name,
                            "mimetype": mimetype,
                            "url": url,
                        }
                    )
            m["attachments"] = enriched_atts

        if any(m.get("attachments") for m in msgs):
            return msgs

        channel_to_indexes: Dict[tuple, List[int]] = {}
        for idx, m in enumerate(msgs):
            model = m.get("model")
            res_id = m.get("res_id")
            if isinstance(model, str) and isinstance(res_id, int):
                key = (model, res_id)
                channel_to_indexes.setdefault(key, []).append(idx)

        if not channel_to_indexes:
            return msgs

        channel_to_atts: Dict[tuple, List[Dict[str, Any]]] = {}

        for key in channel_to_indexes.keys():
            model, res_id = key

            attempts: List[List[Any]] = []

            attempts.append([["res_model", "=", model], ["res_id", "=", res_id]])

            if model == "discuss.channel":
                attempts.append(
                    [["res_model", "=", "mail.channel"], ["res_id", "=", res_id]]
                )
            elif model == "mail.channel":
                attempts.append(
                    [["res_model", "=", "discuss.channel"], ["res_id", "=", res_id]]
                )

            attempts.append([["res_id", "=", res_id]])

            atts: List[Dict[str, Any]] = []
            for dom in attempts:
                try:
                    atts = self.search_read(
                        "ir.attachment",
                        dom,
                        fields=["id", "name", "mimetype", "create_date"],
                        limit=0,
                        order="create_date asc",
                    )
                except Exception:
                    atts = []
                if atts:
                    break

            channel_to_atts[key] = atts

        for key, idx_list in channel_to_indexes.items():
            atts = channel_to_atts.get(key) or []
            if not atts:
                continue

            msg_infos: List[tuple[int, Optional[datetime]]] = []
            for idx in idx_list:
                dt_str = msgs[idx].get("date")
                dt_val: Optional[datetime] = None
                if isinstance(dt_str, str):
                    try:
                        dt_val = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        dt_val = None
                msg_infos.append((idx, dt_val))

            if not msg_infos:
                continue

            default_idx = idx_list[-1]

            for a in atts:
                aid = a.get("id")
                if not isinstance(aid, int):
                    continue

                name = a.get("name") or f"attachment-{aid}"
                mimetype = a.get("mimetype")
                url = f"{base_url}/web/image/{aid}/{quote(str(name))}"

                cd_str = a.get("create_date")
                cd_val: Optional[datetime] = None
                if isinstance(cd_str, str):
                    try:
                        cd_val = datetime.strptime(cd_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        cd_val = None

                target_idx = default_idx

                if cd_val is not None:
                    chosen: Optional[int] = None

                    for idx, msg_dt in msg_infos:
                        if msg_dt is None:
                            continue
                        if msg_dt >= cd_val:
                            chosen = idx
                            break

                    if chosen is None:
                        for idx, msg_dt in reversed(msg_infos):
                            if msg_dt is None:
                                continue
                            if msg_dt <= cd_val:
                                chosen = idx
                                break

                    if chosen is not None:
                        target_idx = chosen

                msgs[target_idx].setdefault("attachments", []).append(
                    {
                        "id": aid,
                        "name": name,
                        "mimetype": mimetype,
                        "url": url,
                    }
                )

        return msgs

    # -------------------------------------------------
    # Live Chat / Discuss – canais e mensagens
    # -------------------------------------------------
    def list_channels(self, limit: int = 50) -> List[Dict[str, Any]]:
        model = self._channel_model
        fields = ["id", "name"]
        for extra in ("channel_type", "public"):
            try:
                self.search_read(model, [], fields=["id", extra], limit=1)
                fields.append(extra)
            except Exception:
                pass
        return self.search_read(model, [], fields=fields, limit=limit, order="id desc")

    def get_messages_by_channel(
        self, channel_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        channel_model = self._channel_model
        domain = [["model", "=", channel_model], ["res_id", "=", channel_id]]
        fields = [
            "id",
            "date",
            "author_id",
            "body",
            "message_type",
            "model",
            "res_id",
            "attachment_ids",
        ]
        msgs = self.search_read(
            "mail.message",
            domain,
            fields=fields,
            limit=limit,
            order="id asc",
        )
        return self._enrich_messages_with_attachments(msgs)

    def get_messages_since_id(
        self, channel_id: int, after_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        channel_model = self._channel_model
        domain = [
            ["model", "=", channel_model],
            ["res_id", "=", channel_id],
            ["id", ">", after_id],
        ]
        fields = [
            "id",
            "date",
            "author_id",
            "body",
            "message_type",
            "model",
            "res_id",
            "attachment_ids",
        ]
        msgs = self.search_read(
            "mail.message",
            domain,
            fields=fields,
            limit=limit,
            order="id asc",
        )
        return self._enrich_messages_with_attachments(msgs)

    def get_message_by_id(self, message_id: int) -> Optional[Dict[str, Any]]:
        rows = self.read(
            "mail.message",
            [message_id],
            fields=[
                "id",
                "date",
                "author_id",
                "body",
                "message_type",
                "model",
                "res_id",
                "attachment_ids",
            ],
        )
        if not rows:
            return None
        enriched = self._enrich_messages_with_attachments(rows)
        return enriched[0]

    def get_messages_by_ids(self, ids: List[int]) -> List[Dict[str, Any]]:
        if not ids:
            return []
        rows = self.read(
            "mail.message",
            ids,
            fields=[
                "id",
                "date",
                "author_id",
                "body",
                "message_type",
                "model",
                "res_id",
                "attachment_ids",
            ],
        )
        return self._enrich_messages_with_attachments(rows)

    def send_message_to_channel(self, channel_id: int, body: str) -> int:
        model = self._channel_model
        result = self.execute_kw(
            model,
            "message_post",
            args=[[channel_id]],
            kwargs={
                "body": body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
            },
        )

        if isinstance(result, list):
            if not result:
                raise RuntimeError("message_post retornou lista vazia")
            result = result[0]

        try:
            return int(result)
        except Exception as e:
            raise RuntimeError(
                f"message_post retornou valor inesperado: {result!r}"
            ) from e

    def send_message_with_attachment(
        self,
        channel_id: int,
        body: str,
        filename: str,
        mimetype: Optional[str],
        data_base64: str,
    ) -> int:
        model = self._channel_model

        safe_body = (body or "").strip()
        if not safe_body:
            safe_body = filename or "Arquivo enviado"

        attach_vals = {
            "name": filename or "arquivo",
            "datas": data_base64,
            "mimetype": mimetype or "application/octet-stream",
            "res_model": model,
            "res_id": channel_id,
        }
        attachment_id = self.create("ir.attachment", attach_vals)

        result = self.execute_kw(
            model,
            "message_post",
            args=[[channel_id]],
            kwargs={
                "body": safe_body,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
                "attachment_ids": [attachment_id],
            },
        )

        if isinstance(result, list):
            if not result:
                raise RuntimeError("message_post retornou lista vazia")
            result = result[0]

        try:
            return int(result)
        except Exception as e:
            raise RuntimeError(
                f"message_post retornou valor inesperado: {result!r}"
            ) from e

    def create_helpdesk_ticket(
        self,
        name: str,
        description: str,
        team_id: Optional[int] = None,
        channel_id: Optional[int] = None,
    ) -> int:
        values: Dict[str, Any] = {"name": name, "description": description}
        if team_id:
            values["team_id"] = team_id
        if channel_id:
            values["x_zion_channel_id"] = channel_id
        return self.create("helpdesk.ticket", values)

    def list_open_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        channel_model = self._channel_model

        now_utc = datetime.now(timezone.utc)
        seven_days_ago = now_utc - timedelta(days=7)
        date_limit = seven_days_ago.strftime("%Y-%m-%d %H:%M:%S")

        msgs = self.search_read(
            "mail.message",
            [
                ["model", "=", channel_model],
                ["date", ">=", date_limit],
            ],
            fields=["id", "date", "res_id"],
            limit=0,
            order="date desc",
        )

        channel_last_date: Dict[int, str] = {}
        for m in msgs:
            cid = m.get("res_id")
            dt = m.get("date")
            if not cid or not dt:
                continue
            if cid not in channel_last_date:
                channel_last_date[cid] = dt

        if not channel_last_date:
            return []

        channel_ids = list(channel_last_date.keys())

        candidate_fields = self._helpdesk_candidate_channel_fields()

        closed_channel_ids: set[int] = set()

        for field_name in candidate_fields:
            try:
                tickets = self.search_read(
                    "helpdesk.ticket",
                    [[field_name, "in", channel_ids]],
                    fields=[field_name],
                    limit=0,
                )
            except Exception:
                continue

            for t in tickets:
                val = t.get(field_name)
                cids: List[int] = []

                if isinstance(val, int):
                    cids = [val]
                elif isinstance(val, (list, tuple)):
                    if len(val) == 2 and isinstance(val[0], (int, str)):
                        try:
                            cids = [int(val[0])]
                        except ValueError:
                            cids = []
                    else:
                        tmp: List[int] = []
                        for elem in val:
                            if isinstance(elem, int):
                                tmp.append(elem)
                            elif isinstance(elem, str) and elem.isdigit():
                                tmp.append(int(elem))
                        if tmp:
                            cids = tmp
                else:
                    cids = []

                for cid in cids:
                    if cid in channel_ids:
                        closed_channel_ids.add(cid)

        open_channel_ids = [cid for cid in channel_ids if cid not in closed_channel_ids]
        if not open_channel_ids:
            return []

        open_channel_ids.sort(
            key=lambda cid: channel_last_date.get(cid, ""),
            reverse=True,
        )

        if limit and len(open_channel_ids) > limit:
            open_channel_ids = open_channel_ids[:limit]

        channels = self.search_read(
            channel_model,
            [["id", "in", open_channel_ids]],
            fields=["id", "name"],
            limit=0,
        )
        name_by_id = {c["id"]: c.get("name", f"Canal {c['id']}") for c in channels}

        sessions: List[Dict[str, Any]] = []
        for cid in open_channel_ids:
            sessions.append(
                {
                    "channel_id": cid,
                    "channel_name": name_by_id.get(cid, f"Canal {cid}"),
                    "last_message_date": channel_last_date.get(cid),
                }
            )
        return sessions

    def close_livechat_channel(self, channel_id: int) -> bool:
        candidates = [
            (self._channel_model, "action_livechat_close"),
            (self._channel_model, "action_close"),
            ("discuss.channel", "action_livechat_close"),
            ("discuss.channel", "action_close"),
            ("mail.channel", "action_livechat_close"),
            ("mail.channel", "action_close"),
        ]

        last_error: Optional[Exception] = None

        for model, method in candidates:
            if not self.model_exists(model):
                continue

            ctx = {
                "active_model": model,
                "active_id": channel_id,
                "active_ids": [channel_id],
            }

            try:
                res = self.execute_kw(
                    model,
                    method,
                    args=[[channel_id]],
                    kwargs={"context": ctx},
                )
                print(
                    f"[ODOO] close_livechat_channel: {model}.{method}({channel_id}) "
                    f"com context={ctx} => {res!r}"
                )
                return bool(res) if res is not None else True
            except Exception as e:
                last_error = e
                print(
                    f"[ODOO] close_livechat_channel: erro em {model}.{method}"
                    f"({channel_id}): {e!r}"
                )
                continue

        try:
            ok = self.write(self._channel_model, [channel_id], {"active": False})
            print(
                f"[ODOO] close_livechat_channel: fallback active=False "
                f"para canal {channel_id} => {ok!r}"
            )
            return bool(ok)
        except Exception as e:
            print(
                f"[ODOO] close_livechat_channel: fallback write(active=False) falhou "
                f"para canal {channel_id}: {e!r}"
            )
            last_error = e

        if last_error:
            raise last_error
        return False