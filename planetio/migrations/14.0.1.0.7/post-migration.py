
def migrate(cr, version):
    """Ensure the farmer_id_code column exists for existing databases."""
    cr.execute(
        """
        ALTER TABLE res_partner
        ADD COLUMN IF NOT EXISTS farmer_id_code VARCHAR;
        """
    )
