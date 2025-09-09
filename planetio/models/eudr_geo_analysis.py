from odoo import models, fields

class CaffeCrudoGeoAnalysis(models.Model):
    _name = 'caffe.crudo.geo.analysis'
    _description = 'Geo Analysis Results from EUDR Tracer'

    # batch_id = fields.Many2one('caffe.crudo.todo.batch', string="Coffee Batch", required=True, ondelete='cascade', unique=True)
    batch_id = fields.Integer()  # fields.Many2one('caffe.crudo.todo.batch', required=True)
    # INFO GENERALI
    name = fields.Char(string="Name")
    latitude = fields.Float(string="Latitude")
    longitude = fields.Float(string="Longitude")
    geojson_data = fields.Text(string="GeoJSON")
    area_analyzed = fields.Float(string="Area Analyzed (ha)")
    analyzed_at = fields.Datetime(string="Analyzed At")
    pass_check = fields.Boolean(string="Pass Check")

    # FARM
    farm_area = fields.Float(string="Farm Area (ha)")
    country_name = fields.Char(string="Country")
    country_code = fields.Char(string="Country Code")
    country_risk = fields.Char(string="Country Risk Level")
    country_value = fields.Float(string="Country Risk Value")

    # ANALISI
    deforestation_free = fields.Boolean(string="Deforestation Free")
    deforestation_area = fields.Float(string="Deforestation Area (ha)")
    built_area_overlap = fields.Float(string="Built Area Overlap (ha)")
    water_overlap = fields.Float(string="Water Overlap (ha)")
    protected_area_overlap = fields.Float(string="Protected Area Overlap (ha)")
    protected_free = fields.Boolean(string="Protected Free")
    reasonable_size = fields.Boolean(string="Reasonable Size")
    data_integrity = fields.Boolean(string="Data Integrity")
    is_on_land = fields.Boolean(string="Is on Land")
    is_not_within_urban_area = fields.Boolean(string="Not Within Urban Area")
    elevation_check = fields.Boolean(string="Elevation Check")
    commodity_region_check = fields.Boolean(string="Commodity Region Check")