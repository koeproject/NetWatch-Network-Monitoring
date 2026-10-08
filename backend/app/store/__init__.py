"""Our own store: time series, latest values, problems, portal accounts.

Separate from the engine's database (CLAUDE.md §3). Two implementations of
StorePort with the same behaviour: SQLite for tests and the demo, Postgres +
TimescaleDB for the appliance.
"""
