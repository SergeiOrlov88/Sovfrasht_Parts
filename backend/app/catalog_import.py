# -*- coding: utf-8 -*-
"""CLI-обёртка импорта каталога: python -m app.catalog_import [файл] [--dry-run]

Логика — в app/services/catalog_import.py. Обёртка нужна, чтобы все три сидера
запускались единообразно (app.catalog_import / app.offers_import / app.repair_import).
"""
from app.services.catalog_import import main

if __name__ == "__main__":
    main()
