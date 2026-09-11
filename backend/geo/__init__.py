"""
Nexus - geopolitical / global-event layer (worldmonitor-shaped).

Local free sources are the mandatory base: Nexus must run correctly with
worldmonitor.app unreachable. The hosted API is optional enrichment that adds
their derived country-instability view on top of a score we compute ourselves.

The output that matters is a single 0-100 ``geo_risk`` score consumed by the
macro gate. Everything else in here exists to justify that number.
"""
