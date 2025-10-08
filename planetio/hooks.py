# your_module/hooks.py
def post_init_hook(cr, registry):
    """
    Ensure ir_attachment has eudr_document_visible with default TRUE.
    Idempotent: safe to run multiple times.
    """
    cr.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'ir_attachment'
                  AND column_name = 'eudr_document_visible'
            ) THEN
                ALTER TABLE ir_attachment
                    ADD COLUMN eudr_document_visible boolean;
            END IF;

            -- Set default and backfill NULLs
            ALTER TABLE ir_attachment
                ALTER COLUMN eudr_document_visible SET DEFAULT TRUE;

            UPDATE ir_attachment
               SET eudr_document_visible = TRUE
             WHERE eudr_document_visible IS NULL;
        END$$;
    """)
