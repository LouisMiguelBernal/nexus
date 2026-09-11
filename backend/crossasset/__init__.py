"""
Nexus - cross-asset context layer.

OpenBB-shaped coverage (equity / index / rates / currency / commodity / macro /
options / screener) pulled from keyless public endpoints, used as *context* for
the perp engines. Nothing in here is tradable: no symbol from this package may
reach an exchange code path.
"""
