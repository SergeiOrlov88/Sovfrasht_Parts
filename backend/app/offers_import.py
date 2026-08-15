# -*- coding: utf-8 -*-
"""CLI-обёртка импорта предложений: python -m app.offers_import [файл] [--dry-run]

Логика — в app/services/offers_import.py.
"""
from app.services.offers_import import main

if __name__ == "__main__":
    main()
