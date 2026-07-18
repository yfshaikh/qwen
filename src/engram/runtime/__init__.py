"""The composition root: turns environment/.env config into a wired `Engram`.

`core` must not import adapters or `app.config` — this package is where that
wiring happens instead. See `runtime.factory.from_env`.
"""
