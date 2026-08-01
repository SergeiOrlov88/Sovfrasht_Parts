# -*- coding: utf-8 -*-
"""CuratedProvider — предложения из курируемого списка в БД (C1, FR-PRO-01/02).

Единственная реализация на MVP. Цены и сроки справочные: они заведены вручную
и помечены source=curated/demo, чтобы потом отличаться от полученных по API.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.suppliers.base import Offer, SupplierInfo, SupplierProvider
from app.models.catalog import Part, Supplier, SupplierOffer

# Сначала то, что есть на складе, потом дешёвое; «нет в наличии» — в конец.
_STOCK_ORDER = {"in": 0, "low": 1, "out": 2, None: 3}


def _price_key(price: str | None) -> float:
    """Цены заведены строками («$1 190», «€820»). Для сортировки достаём число;
    если не получилось — отправляем в конец, а не роняем выдачу."""
    if not price:
        return float("inf")
    digits = "".join(ch for ch in price if ch.isdigit())
    return float(digits) if digits else float("inf")


class CuratedProvider(SupplierProvider):
    name = "curated"

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_offers(self, part: Part) -> list[Offer]:
        rows = (await self._db.execute(
            select(SupplierOffer, Supplier)
            .join(Supplier, Supplier.id == SupplierOffer.supplier_id)
            .where(SupplierOffer.part_id == part.id)
        )).all()

        offers = [
            Offer(
                supplier=SupplierInfo(name=supplier.name, type=supplier.type,
                                      url=supplier.url, region=supplier.region),
                price=offer.price,
                lead_time=offer.lead_time,
                stock_status=offer.stock_status,
                deep_link=offer.deep_link,
                source=offer.source,
                fetched_at=offer.fetched_at,
                part_id=part.id,
            )
            for offer, supplier in rows
        ]
        offers.sort(key=lambda o: (_STOCK_ORDER.get(o.stock_status, 3), _price_key(o.price)))
        return offers
