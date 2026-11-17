Schema v1 is defined by the SQLAlchemy models and created at startup via Base.metadata.create_all. For this local small application no destructive migration is run. Back up named db-data before modifying schemas.

Schema v2 (2026-11-17) adds tables series / series_studies / series_ledger for shared significance budgets (研究系列). The change is additive only; existing tables are untouched and create_all applies it automatically on next backend start.
