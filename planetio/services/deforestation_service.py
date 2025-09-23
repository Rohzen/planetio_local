from odoo import models, _
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class DeforestationService(models.AbstractModel):
    _name = 'deforestation.service'
    _description = 'Deforestation Service Orchestrator'

    _REGISTRY = {
        'gfw':   'deforestation.provider.gfw',
        'plant4':'deforestation.provider.plant4',
    }

    def get_enabled_providers(self):
        ctx_override = self.env.context.get('deforestation_providers_override')
        if ctx_override:
            if isinstance(ctx_override, str):
                forced = [ctx_override]
            elif isinstance(ctx_override, (list, tuple, set)):
                forced = list(ctx_override)
            else:
                forced = [ctx_override]
            forced = [code for code in forced if code in self._REGISTRY]
            if forced:
                return forced

        ICP = self.env['ir.config_parameter'].sudo()
        # New single-provider selector takes precedence when set
        selected = (ICP.get_param('planetio.deforestation_provider') or '').strip()
        if selected and selected in self._REGISTRY:
            return [selected]

        raw = (ICP.get_param('deforestation.providers') or '').strip()
        if not raw:
            return ['gfw']  # default e preferito
        # normalizza, rimuovi sconosciuti, preserva ordine ma imponi gfw in testa se presente
        items = [p.strip() for p in raw.split(',') if p.strip()]
        items = [p for p in items if p in self._REGISTRY]
        if 'gfw' in items:
            items = ['gfw'] + [p for p in items if p != 'gfw']
        return items or ['gfw']

    def analyze_line(self, line):
        providers = self.get_enabled_providers()
        if not providers:
            raise UserError(_("Nessun provider di deforestazione configurato."))

        errors = []
        for provider_code in providers:
            provider = self.env[self._REGISTRY[provider_code]]
            try:
                provider.check_prerequisites()
            except UserError as ue:
                errors.append(_('Provider %(p)s: %(m)s') % {'p': provider_code, 'm': str(ue)})
                continue

            try:
                result = provider.analyze_line(line)
            except UserError as ue:
                errors.append(_('Provider %(p)s: %(m)s') % {'p': provider_code, 'm': str(ue)})
                continue
            except Exception as ex:
                _logger.exception("Provider %s failed during analyze_line", provider_code)
                errors.append(_('Provider %(p)s errore inatteso: %(m)s') % {'p': provider_code, 'm': str(ex)})
                continue

            if isinstance(result, dict):
                meta = result.setdefault('meta', {})
                meta.setdefault('provider', provider_code)
            return result

        if errors:
            raise UserError(_('Analisi deforestazione non riuscita: %s') % '; '.join(errors))
        raise UserError(_("Analisi deforestazione non riuscita: nessun provider disponibile."))

    def analyze_records(self, eudr_import_rec, providers):
        errors, details = [], []
        lines = getattr(eudr_import_rec, 'line_ids', False)
        if not lines:
            raise UserError(_("Nessuna riga da analizzare."))

        for provider_code in providers:
            provider = self.env[self._REGISTRY[provider_code]]
            try:
                provider.check_prerequisites()
            except UserError as ue:
                errors.append({'level':'error','provider':provider_code,'message':str(ue)})
                continue

            for line in lines:
                try:
                    res = provider.analyze_line(line)
                    if isinstance(res, dict):
                        meta = res.setdefault('meta', {})
                        meta.setdefault('provider', provider_code)
                    line.external_message = res.get('message') or _("OK")
                    details.append({'provider':provider_code,'line_id':line.id,'result':res})
                except UserError as ue:
                    line.external_message = str(ue)
                    errors.append({'level':'error','provider':provider_code,'line_id':line.id,'message':str(ue)})
                except Exception as ex:
                    _logger.exception("Provider %s failed on line %s", provider_code, line.id)
                    line.external_message = _("Errore inatteso dal provider %(p)s: %(m)s", {'p': provider_code, 'm': str(ex)})
                    errors.append({'level':'error','provider':provider_code,'line_id':line.id,'message':str(ex)})

        return {'errors': errors, 'details': details}