from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Ensure ``ir_attachment`` carries the ``eudr_document_visible`` column."""
    if not version:
        return

    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'ir_attachment'
           AND column_name = 'eudr_document_visible'
        """
    )
    if cr.fetchone():
        return

    cr.execute(
        """
        ALTER TABLE ir_attachment
        ADD COLUMN eudr_document_visible boolean DEFAULT TRUE
        """
    )
    # The DEFAULT clause populates existing rows, but ensure NULLs are fixed if
    # the database engine does not backfill them automatically.
    cr.execute(
        """
        UPDATE ir_attachment
           SET eudr_document_visible = TRUE
         WHERE eudr_document_visible IS NULL
        """
    )

    # Reflect the default at ORM level for running environments.
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.attachment']._fields['eudr_document_visible'].default = True
