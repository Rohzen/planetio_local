# -*- coding: utf-8 -*-
import base64
import json

from odoo import models, _
from odoo.exceptions import UserError


class EUDRDeclaration(models.Model):
    _inherit = "eudr.declaration"

    def _get_osapiens_client(self):
        from ..services.osapiens_client import OsapiensClient
        return OsapiensClient(self.env)

    @staticmethod
    def _is_geojson_attachment(attachment):
        name = (attachment.name or "").lower()
        return (
            attachment.type == "binary"
            and (
                (attachment.mimetype or "").lower() == "application/geo+json"
                or name.endswith(".geojson")
            )
        )

    @staticmethod
    def _decode_geojson_attachment(attachment):
        if attachment.type != "binary":
            raise UserError(
                _("Attachment %s is not a binary file.")
                % (attachment.display_name or attachment.name)
            )
        datas = attachment.with_context(bin_size=False).datas
        if not datas:
            raise UserError(
                _("Attachment %s does not contain any data.")
                % (attachment.display_name or attachment.name)
            )
        try:
            payload = base64.b64decode(datas)
        except Exception as exc:
            raise UserError(
                _("Cannot decode attachment %s (%s).")
                % (attachment.display_name or attachment.name, exc)
            )
        try:
            geojson = json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise UserError(
                _("Attachment %s does not contain valid JSON (%s).")
                % (attachment.display_name or attachment.name, exc)
            )
        if not isinstance(geojson, dict):
            raise UserError(
                _("Attachment %s does not contain a GeoJSON object.")
                % (attachment.display_name or attachment.name)
            )
        return geojson

    @staticmethod
    def _geojson_features(geojson):
        gtype = geojson.get("type") if isinstance(geojson, dict) else None
        if gtype == "FeatureCollection":
            features = geojson.get("features") or []
            return [f for f in features if isinstance(f, dict)]
        if gtype == "Feature" and isinstance(geojson, dict):
            return [geojson]
        if gtype and isinstance(geojson, dict):
            return [{"type": "Feature", "properties": {}, "geometry": geojson}]
        return []

    def action_osapiens_send_geojson(self):
        Attachment = self.env["ir.attachment"].sudo()
        for declaration in self:
            attachments = Attachment.search(
                [
                    ("res_model", "=", declaration._name),
                    ("res_id", "=", declaration.id),
                    ("type", "=", "binary"),
                    "|",
                    ("mimetype", "=", "application/geo+json"),
                    ("name", "ilike", ".geojson"),
                ]
            )
            if not attachments:
                raise UserError(
                    _("No GeoJSON attachment found on %s.") % (declaration.display_name,)
                )

            geojson_attachments = [
                att for att in attachments if self._is_geojson_attachment(att)
            ] or list(attachments)

            try:
                client = declaration._get_osapiens_client()
            except ValueError as exc:
                raise UserError(str(exc))

            sent_plots = []
            for attachment in geojson_attachments:
                geojson = self._decode_geojson_attachment(attachment)
                features = self._geojson_features(geojson)
                if not features:
                    raise UserError(
                        _("Attachment %s does not contain any GeoJSON feature.")
                        % (attachment.display_name or attachment.name)
                    )

                for index, feature in enumerate(features, start=1):
                    geometry = feature.get("geometry") if isinstance(feature, dict) else None
                    if not isinstance(geometry, dict) or not geometry.get("type"):
                        raise UserError(
                            _("Feature %s in attachment %s has no valid geometry.")
                            % (index, attachment.display_name or attachment.name)
                        )

                    properties = feature.get("properties") if isinstance(feature, dict) else {}
                    if not isinstance(properties, dict):
                        properties = {}
                    plot_id = (
                        properties.get("plotId")
                        or properties.get("plot_id")
                        or properties.get("name")
                        or f"{declaration.name or declaration.id}-plot-{index}"
                    )
                    plot_id = str(plot_id)

                    metadata = properties.copy()
                    metadata.update(
                        {
                            "declarationId": declaration.id,
                            "declarationName": declaration.name,
                            "attachmentId": attachment.id,
                            "attachmentName": attachment.name,
                        }
                    )
                    try:
                        client.create_or_update_plot(plot_id, geometry, metadata=metadata)
                    except Exception as exc:
                        raise UserError(
                            _("Failed to send GeoJSON for plot %(plot)s: %(error)s")
                            % {"plot": plot_id, "error": exc}
                        )
                    sent_plots.append(plot_id)

            if sent_plots:
                declaration.message_post(
                    body=_(
                        "Sent %(count)s GeoJSON feature(s) to oSapiens: %(plots)s"
                    )
                    % {
                        "count": len(sent_plots),
                        "plots": ", ".join(sorted(set(sent_plots))),
                    }
                )
        return True
