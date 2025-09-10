# -*- coding: utf-8 -*-
import abc
from typing import Any, Dict, List, Optional, Tuple

class DeforestationProvider(abc.ABC):
    """Provider interface for querying deforestation status over an AOI (GeoJSON).

    Implementations should return a normalized response with at least:
      - alerts: List[Dict]  # each item minimally: {'date': 'YYYY-MM-DD', 'area_ha': float, 'lat': float, 'lon': float, 'source': str}
      - metrics: Dict[str, Any]  # aggregated KPIs like {'alert_count': int, 'area_ha_total': float}
      - meta: Dict[str, Any]     # provider-specific metadata

    All providers must accept the same method signature.
    """
    name: str = "base"

    @abc.abstractmethod
    def get_status(
        self,
        aoi_geojson: Dict[str, Any],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Return deforestation alerts and metrics for the given AOI.

        Dates should be ISO strings 'YYYY-MM-DD'. If omitted, the provider should use a sensible default
        (e.g., last 30/90 days) or return all available alerts with pagination options in **kwargs.
        """
        raise NotImplementedError
