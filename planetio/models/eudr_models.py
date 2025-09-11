
from odoo import models, fields, api, _, _
from odoo.exceptions import UserError, ValidationError
import json
import math
import urllib.parse

try:
    from shapely.geometry import Point, mapping
    from shapely.ops import transform
    from pyproj import CRS, Transformer
except ImportError:
    # Se le librerie non sono installate, la funzionalità non sarà disponibile.
    # In un ambiente di produzione, sarebbe meglio loggare un avviso.
    Point = None


try:
    from pyproj import Geod, Transformer, CRS  # optional but recommended
except Exception:
    Geod = None
    Transformer = None
    CRS = None

class EUDRStage(models.Model):
    _name = "eudr.stage"
    _description = "CRM Stages"
    _rec_name = 'name'
    _order = "sequence, name, id"

    name = fields.Char('Stage Name', required=True, translate=True)
    sequence = fields.Integer('Sequence', default=1, help="Used to order stages. Lower is better.")

class EUDRDeclaration(models.Model):
    _name = "eudr.declaration"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "EUDR Declaration"

    datestamp = fields.Datetime(string="Datestamp", default=lambda self: fields.Datetime.now())
    name = fields.Char(required=True)
    stage_id = fields.Many2one('eudr.stage', string='Stage', index=True, tracking=True)
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Float(compute="_compute_area_ha", store=True, readonly=True)

    geo_type = fields.Selection([("point","Point"),("polygon","Polygon")])
    geometry = fields.Text()  # optional: header-level geometry if you ever use it
    source_attachment_id = fields.Many2one("ir.attachment")
    line_ids = fields.One2many("eudr.declaration.line", "declaration_id", string="Lines")

    # DDS
    # internal_ref = record.protocol_number or f'Batch-{record.id}',
    # activity_type = 'IMPORT',
    # company_name = company.name or 'Company',
    # company_country = company_country,
    # company_address = company_address,
    # eori_value = eori_value,
    # hs_heading = '090111',
    # description_of_goods = 'Green coffee beans',
    # net_weight_kg = net_weight_kg,
    # producer_country = (record.country_code or 'BR').upper(),
    # producer_name = record.name or 'Unknown Producer',
    # geojson_b64 = geojson_b64,
    # operator_type = 'OPERATOR',
    # country_of_activity = company_country,
    # border_cross_country = company_country,
    # qdate = getattr(record, 'questionnaire_date', False)

    attachment_ids = fields.One2many(
        'ir.attachment', 'res_id',
        string='Attachments',
        domain=lambda self: [('res_model', '=', self._name)],
        help="Files linked to this declaration."
    )
    eudr_type_override = fields.Selection([
        ('trader', 'Trader'),
        ('operator', 'Operator')
    ], string="EUDR Role (Mixed)", default='trader', help="Specify whether you're acting as Trader or Operator for this batch.")
    partner_id = fields.Many2one(
        'res.partner', string="Partner"
    )
    eudr_third_party_client_id = fields.Many2one(
        'res.partner', string="Client (3rd Party Trader)", help="Client on behalf of whom the DDS is being submitted."
    )
    eudr_company_type = fields.Selection([
        ('trader', 'Trader'),
        ('operator', 'Operator'),
        ('mixed', 'Mixed'),
        ('third_party_trader', 'Third-party Trader')
    ], string="Company Type",)
    # Dati generali (DDS TRACES)
    activity_type = fields.Selection(
        [
            ('import', 'Import'),
            ('export', 'Export'),
            ('domestic', 'Domestic'),
        ], string="Activity", default='import')
    operator_name = fields.Char(string="Operator")
    extra_info = fields.Text(string="Additional info")
    hs_code = fields.Selection(
        [
            ('0901',    '0901 – Coffee, whether or not roasted or decaffeinated; coffee husks and skins; coffee substitutes containing coffee'),
            ('090111',  '0901 11 – non-decaffeinated'),
            ('090112',  '0901 12 – decaffeinated'),
            ('090121',  '0901 21 – non-decaffeinated'),
            ('090122',  '0901 22 – decaffeinated'),
            ('090190',  '0901 90 – others'),
        ], string="HS Code")
    product_id  = fields.Many2one('product.product', string="Prodotto")
    product_description = fields.Char(string="Description of raw materials or products")
    net_mass_kg = fields.Float(string="Net mass (kg)", digits=(16, 3))
    common_name = fields.Char(string="Common name")
    producer_name = fields.Char(string="Producer name")

    # ---------------------- helpers ----------------------

    @staticmethod
    def _safe_json_load(s):
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    @staticmethod
    def _iter_geojson_geometries(obj):
        """
        Yields raw GeoJSON geometry dicts from:
        - Geometry
        - Feature with .geometry
        - FeatureCollection with .features[*].geometry
        Anything else is ignored.
        """
        if not obj:
            return
        t = obj.get("type")
        if t in ("Point", "Polygon", "MultiPolygon", "MultiPoint", "LineString", "MultiLineString"):
            yield obj
        elif t == "Feature" and isinstance(obj.get("geometry"), dict):
            yield obj["geometry"]
        elif t == "FeatureCollection" and isinstance(obj.get("features"), list):
            for f in obj["features"]:
                if isinstance(f, dict) and isinstance(f.get("geometry"), dict):
                    yield f["geometry"]

    @staticmethod
    def _poly_rings_lonlat(geom):
        """
        Returns list of polygons, each polygon is a list of linear rings,
        each ring is a list of (lon, lat) tuples. Holes are included but area is computed geodesically later.
        """
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if gtype == "Polygon" and isinstance(coords, list):
            return [coords]  # [ [ [lon,lat], ... ] , hole?, ... ]
        if gtype == "MultiPolygon" and isinstance(coords, list):
            return coords    # [ polygon1_rings, polygon2_rings, ... ]
        return []

    # ----------------- geodesic area via pyproj.Geod -----------------

    @staticmethod
    def _geodesic_area_m2_of_polygons(polygons_rings):
        """
        polygons_rings: iterable of polygons, each polygon is list of rings (outer + holes),
        where each ring is list of [lon, lat] pairs.
        Uses WGS84 ellipsoid. Returns total absolute area in m².
        """
        if not Geod:
            return None  # signal that geodesic computation isn't available
        geod = Geod(ellps="WGS84")
        total = 0.0
        for rings in polygons_rings:
            if not rings:
                continue
            # exterior ring first per GeoJSON spec
            lon_ex, lat_ex = zip(*[(pt[0], pt[1]) for pt in rings[0] if isinstance(pt, (list, tuple)) and len(pt) >= 2])
            # area is negative if ring is counterclockwise; take absolute
            area_ex, _ = geod.polygon_area_perimeter(lon_ex, lat_ex)
            poly_area = abs(area_ex)
            # subtract holes if any
            for hole in rings[1:]:
                if not hole:
                    continue
                lon_h, lat_h = zip(*[(pt[0], pt[1]) for pt in hole if isinstance(pt, (list, tuple)) and len(pt) >= 2])
                area_h, _ = geod.polygon_area_perimeter(lon_h, lat_h)
                poly_area -= abs(area_h)
            total += max(0.0, poly_area)
        return total

    # -------------- convex hull of points (fallback / points-only) --------------

    @staticmethod
    def _convex_hull(points_xy):
        """
        Monotone chain convex hull. points_xy is a list of (x, y).
        Returns hull as list of (x, y) in CCW order without duplicate closing point.
        """
        pts = sorted(set(points_xy))
        if len(pts) <= 1:
            return pts

        def cross(o, a, b):
            return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

        lower = []
        for p in pts:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)

        upper = []
        for p in reversed(pts):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)

        return lower[:-1] + upper[:-1]

    @staticmethod
    def _shoelace_area_m2(coords_xy):
        """Planar polygon area by shoelace formula. coords_xy is list of (x, y)."""
        if len(coords_xy) < 3:
            return 0.0
        area = 0.0
        n = len(coords_xy)
        for i in range(n):
            x1, y1 = coords_xy[i]
            x2, y2 = coords_xy[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        return abs(area) * 0.5

    @staticmethod
    def _project_points_to_meters(lonlat_list):
        """
        Projects (lon, lat) to meters.
        Prefers UTM via pyproj; otherwise uses local equirectangular approximation.
        Returns list of (x, y) in meters.
        """
        if not lonlat_list:
            return []

        # centroid to choose projection
        lon0 = sum(p[0] for p in lonlat_list) / len(lonlat_list)
        lat0 = sum(p[1] for p in lonlat_list) / len(lonlat_list)

        # If pyproj available, choose UTM zone based on centroid
        if Transformer and CRS:
            zone = int(math.floor((lon0 + 180.0) / 6.0) + 1)
            north = lat0 >= 0.0
            epsg = 32600 + zone if north else 32700 + zone
            try:
                transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
                return [transformer.transform(lon, lat) for lon, lat in lonlat_list]
            except Exception:
                pass  # fall through to equirectangular

        # equirectangular approximation (good for compact clusters)
        R = 6371008.8
        lat0_rad = math.radians(lat0)
        x0 = R * math.radians(lon0) * math.cos(lat0_rad)
        y0 = R * math.radians(lat0)
        out = []
        for lon, lat in lonlat_list:
            x = R * math.radians(lon) * math.cos(lat0_rad)
            y = R * math.radians(lat)
            out.append((x - x0, y - y0))  # shift near origin to improve stability
        return out

    # ------------------ main compute ------------------

    @api.depends("line_ids.geometry", "line_ids.geo_type")
    def _compute_area_ha(self):
        for rec in self:
            polygons = []     # list of polygons, each polygon is list of rings (list of [lon, lat])
            points_ll = []    # list of (lon, lat)

            # collect geometries from lines
            for line in rec.line_ids:
                gobj = self._safe_json_load(line.geometry)
                if not gobj:
                    continue
                for geom in self._iter_geojson_geometries(gobj):
                    gtype = geom.get("type")
                    if gtype in ("Polygon", "MultiPolygon"):
                        polygons.extend(self._poly_rings_lonlat(geom))
                    elif gtype == "Point":
                        coords = geom.get("coordinates") or []
                        if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                            points_ll.append((float(coords[0]), float(coords[1])))
                    elif gtype == "MultiPoint":
                        coords = geom.get("coordinates") or []
                        for pt in coords:
                            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                                points_ll.append((float(pt[0]), float(pt[1])))
                    # LineString/MultiLineString are ignored for area

            area_m2 = 0.0

            # priority 1: true polygons, computed geodesically if possible
            if polygons:
                area_geo = self._geodesic_area_m2_of_polygons(polygons)
                if area_geo is not None:
                    area_m2 = area_geo
                else:
                    # fallback: project rings to meters and apply shoelace with holes
                    total = 0.0
                    for rings in polygons:
                        if not rings:
                            continue
                        exterior = [(pt[0], pt[1]) for pt in rings[0] if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                        ex_xy = self._project_points_to_meters(exterior)
                        poly_area = self._shoelace_area_m2(ex_xy)
                        for hole in rings[1:]:
                            hole_ll = [(pt[0], pt[1]) for pt in hole if isinstance(pt, (list, tuple)) and len(pt) >= 2]
                            hole_xy = self._project_points_to_meters(hole_ll)
                            poly_area -= self._shoelace_area_m2(hole_xy)
                        total += max(0.0, poly_area)
                    area_m2 = total

            # priority 2: no polygons → use convex hull of points if >= 3
            elif len(points_ll) >= 3:
                pts_xy = self._project_points_to_meters(points_ll)
                hull = self._convex_hull(pts_xy)
                area_m2 = self._shoelace_area_m2(hull)

            # else: area remains 0.0

            rec.area_ha = (area_m2 / 10000.0) if area_m2 > 0.0 else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        # Ensure every declaration gets a sequence-generated name
        for vals in (vals_list or []):
            if not vals.get('name'):
                seq = (self.env['ir.sequence'].next_by_code('eudr.declaration')
                       or self.env['ir.sequence'].next_by_code('planetio.eudr.declaration')
                       or 'EUDR-SEQ')
                vals['name'] = seq
        return super(EUDRDeclaration, self).create(vals_list)


    def action_open_excel_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Excel Import Wizard',
            'res_model': 'excel.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_template_id': self.env.ref('planetio.tmpl_eudr_declaration').id,
            },
        }



    def action_export_geojson(self):
        """Esporta una FeatureCollection con tutte le geometrie delle linee."""
        self.ensure_one()
        features = []
        for line in self.line_ids:
            if not line.geometry:
                continue
            try:
                geom = json.loads(line.geometry)
            except Exception:
                continue
            props = {
                "name": line.name,
                "farmer_name": line.farmer_name,
                "farm_name": line.farm_name,
                "area_ha": line.area_ha,
                "geo_type": line.geo_type,
            }
            features.append({"type": "Feature", "geometry": geom, "properties": props})
        payload = {"type": "FeatureCollection", "features": features}
        return {
            "type": "ir.actions.act_url",
            "url": "data:application/json," + json.dumps(payload),
            "target": "new",
        }

    def open_otp_wizard(self):
        self.ensure_one()

        # Simula invio OTP
        self.message_post(body=_("OTP sent to the phone number entered during certification."))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'otp.verification.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_batch_id': self.id
            }
        }

    # messo in services per evitare dipendenze circolari e troppe modifiche al codice esistente
    def action_transmit_dds(self):
        from ..services.eudr_adapter_odoo import submit_dds_for_batch
        for record in self:
            dds_id = submit_dds_for_batch(record)


    def action_open_import_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'excel.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'eudr.declaration',
                'active_id': self.id,
            }
        }
class EUDRDeclarationLine(models.Model):
    _name = "eudr.declaration.line"
    _description = "EUDR Declaration Line"
    # _inherit = ['mail.thread', 'mail.activity.mixin']

    declaration_id = fields.Many2one("eudr.declaration", ondelete="cascade")
    name = fields.Char()
    farmer_name = fields.Char()
    farmer_id_code = fields.Char()
    tax_code = fields.Char()
    country = fields.Char()
    region = fields.Char()
    municipality = fields.Char()
    farm_name = fields.Char()
    area_ha = fields.Char()
    geo_type = fields.Selection([("point","Point"),("polygon","Polygon")])
    geometry = fields.Text()  # GeoJSON string

    external_uid = fields.Char(index=True)
    external_status = fields.Selection([
        ('ok', 'OK'),
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('error', 'Error'),
    ], readonly=True)
    external_message = fields.Char()
    external_properties_json = fields.Text()
    external_http_code = fields.Integer(readonly=True)
    external_message_short = fields.Char(readonly=True)
    external_ok = fields.Boolean(
        string="OK",
        readonly=True,
    )

    def action_visualize_area_on_map(self):
        """
        Questo metodo viene chiamato quando si preme il pulsante.
        Calcola un'area di 50mq attorno a un punto e la apre in geojson.io.
        """
        # if not Point:
        #     raise UserError("Le librerie 'shapely' e 'pyproj' sono necessarie. "
        #                     "Per favore, installale eseguendo: pip install shapely pyproj")

        # Assicuriamoci che l'operazione venga eseguita per un solo record alla volta.
        self.ensure_one()

        if not self.geometry:
            raise UserError("Il campo 'Geometria' è vuoto. Inserisci le coordinate GeoJSON.")

        try:
            geo_data = json.loads(self.geometry)
            if geo_data.get('type') != 'Point' or 'coordinates' not in geo_data:
                raise ValueError()

            lon, lat = geo_data['coordinates']
        except (json.JSONDecodeError, ValueError):
            raise UserError("Il formato del GeoJSON nel campo 'Geometria' non è valido. "
                            "Assicurati che sia un punto valido, ad es: "
                            '{"type": "Point", "coordinates": [9.19, 45.46]}')

        # --- Calcolo Geospaziale ---
        # 1. Calcoliamo il raggio di un cerchio con area di 50 mq.
        #    Area = π * r^2  =>  r = sqrt(Area / π)
        area_mq = 50.0
        radius_in_meters = math.sqrt(area_mq / math.pi)

        # 2. Le coordinate GeoJSON sono in WGS84 (gradi). Per creare un buffer in metri,
        #    dobbiamo proiettare il punto in un sistema di coordinate che usi i metri,
        #    come UTM (Universal Transverse Mercator).

        # Definiamo il sistema di coordinate di partenza (WGS84)
        wgs84 = CRS("EPSG:4326")

        # Troviamo la zona UTM corretta per la longitudine del punto
        utm_zone = int((lon + 180) / 6) + 1
        utm_crs_str = f"EPSG:326{utm_zone}" if lat >= 0 else f"EPSG:327{utm_zone}"
        utm = CRS(utm_crs_str)

        # Creiamo i trasformatori per passare da WGS84 a UTM e viceversa
        transformer_to_utm = Transformer.from_crs(wgs84, utm, always_xy=True)
        transformer_to_wgs84 = Transformer.from_crs(utm, wgs84, always_xy=True)

        # 3. Trasformiamo il punto in coordinate UTM (metri)
        point_utm = transformer_to_utm.transform(lon, lat)

        # 4. Creiamo il buffer (l'area circolare) in metri
        shapely_point_utm = Point(point_utm)
        buffered_area_utm = shapely_point_utm.buffer(radius_in_meters)

        # 5. Riproiettiamo il poligono risultante di nuovo in WGS84 (gradi) per visualizzarlo
        buffered_area_wgs84 = transform(transformer_to_wgs84.transform, buffered_area_utm)

        # 6. Convertiamo il poligono di shapely in un dizionario GeoJSON
        final_geojson = mapping(buffered_area_wgs84)

        # --- Costruzione dell'URL ---
        # Codifichiamo il GeoJSON per inserirlo nell'URL
        encoded_geojson = urllib.parse.quote(json.dumps(final_geojson))

        # Costruiamo l'URL finale per geojson.io
        url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"

        # Restituiamo un'azione di Odoo per aprire l'URL in una nuova scheda
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_visualize_point_on_map(self):
        """
        Questo metodo viene chiamato quando si preme il pulsante.
        Visualizza il singolo punto GeoJSON su geojson.io.
        """
        self.ensure_one()

        if not self.geometry:
            raise UserError("Il campo 'Geometria' è vuoto. Inserisci le coordinate GeoJSON.")

        try:
            # Verifichiamo che il JSON sia valido e di tipo 'Point'
            geo_data = json.loads(self.geometry)
            if geo_data.get('type') != 'Point' or 'coordinates' not in geo_data:
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise UserError("Il formato del GeoJSON nel campo 'Geometria' non è valido. "
                            "Assicurati che sia un punto valido, ad es: "
                            '{"type": "Point", "coordinates": [9.19, 45.46]}')

        # --- Costruzione dell'URL ---
        # Codifichiamo il GeoJSON originale (contenuto nel campo geometry) per inserirlo nell'URL
        encoded_geojson = urllib.parse.quote(self.geometry)

        # Costruiamo l'URL finale per geojson.io
        url = f"https://geojson.io/#data=data:application/json,{encoded_geojson}"

        # Restituiamo un'azione di Odoo per aprire l'URL in una nuova scheda
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }