from odoo import models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def action_open_attachment(self):
        """Open the attachment content or URL in a new browser tab."""
        self.ensure_one()

        if self.type == "url" and self.url:
            return {
                "type": "ir.actions.act_url",
                "url": self.url,
                "target": "new",
            }

        # Default to opening the stored binary content.
        # ``download=false`` lets the browser preview supported mimetypes.
        url = f"/web/content/{self.id}?download=false"
        if self.access_token:
            url += f"&access_token={self.access_token}"
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }
