from odoo import models, fields
import base64, json

class ExcelImportWizard(models.TransientModel):
    _name = "excel.import.wizard"
    _description = "Excel Import Wizard"

    file_data = fields.Binary(string="File", required=True, attachment=False)
    file_name = fields.Char(string="Filename")
    template_id = fields.Many2one("excel.import.template", required=True)

    step = fields.Selection(
        [("upload","Upload"),
         ("map","Mapping"),
         ("validate","Validate"),
         ("confirm","Confirm")],
        default="upload"
    )

    job_id = fields.Many2one("excel.import.job")
    mapping_json = fields.Text(readonly=True)
    preview_json = fields.Text(readonly=True)
    result_json = fields.Text(readonly=True)
    analysis_json = fields.Text(readonly=True)

    def action_analyze_external(self):
        self.ensure_one()
        data = self.env["planetio.tracer.api"].analyze_job_and_update(self.job_id)
        self.analysis_json = json.dumps(data, ensure_ascii=False, indent=2)
        self.step = "validate"
        return {
            "type": "ir.actions.act_window",
            "res_model": "excel.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def _create_attachment(self):
        self.ensure_one()
        return self.env["ir.attachment"].create({
            "name": self.file_name or "upload.xlsx",
            "datas": self.file_data,
            "res_model": "excel.import.job",
            "res_id": 0,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        })

    def action_detect_and_map(self):
        self.ensure_one()
        attachment = self._create_attachment()

        job = self.env["excel.import.job"].create({
            "attachment_id": attachment.id,
            "template_id": self.template_id.id,
        })
        attachment.write({"res_id": job.id})

        sheet, score = self.env["excel.import.service"].pick_best_sheet(job)
        job.sheet_name = sheet
        job.log_info(f"Selected sheet: {sheet} (score {score:.2f})")

        mapping, preview = self.env["excel.import.service"].propose_mapping(job)
        job.mapping_json = json.dumps(mapping, ensure_ascii=False)
        job.preview_json = json.dumps(preview, ensure_ascii=False)
        job.status = "mapped"

        self.job_id = job.id
        self.mapping_json = job.mapping_json
        self.preview_json = job.preview_json
        self.step = "map"

        return {
            "type": "ir.actions.act_window",
            "res_model": "excel.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_validate(self):
        self.ensure_one()
        transformed = self.env["excel.import.service"].transform_and_validate(self.job_id)
        self.job_id.result_json = transformed
        self.result_json = transformed
        self.job_id.status = "validated"
        self.step = "validate"
        return {
            "type": "ir.actions.act_window",
            "res_model": "excel.import.wizard",
            "view_mode": "form",
            "res_id": self.id,
            "target": "new",
        }

    def action_confirm(self):
        self.ensure_one()
        created = self.env["excel.import.service"].create_records(self.job_id)
        self.job_id.log_info(f"Created/updated records: {created}")
        self.job_id.status = "done"
        self.step = "confirm"
        return {"type":"ir.actions.act_window_close"}
