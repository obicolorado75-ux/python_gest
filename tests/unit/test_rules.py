"""Tests des règles de calcul du domaine (§5.14, §7.4)."""
import pytest

from gestdepot.domain import rules


class TestRules:
    def test_conversion_t01(self):
        # T01 : 1 casier = 24 bouteilles
        assert rules.convert_quantity(1, 24) == 24

    def test_conversion_mixte_t03(self):
        # 2 casiers + 3 bouteilles = 51 (T03)
        assert rules.convert_quantity(2, 24, base_qty=3) == 51

    def test_negative_quantity_refused(self):
        with pytest.raises(ValueError):
            rules.convert_quantity(-1, 24)

    def test_marge(self):
        assert rules.margin_unit(500, 350) == 150
        assert rules.margin_rate(150, 350) == pytest.approx(42.9)
        assert rules.markup_rate(150, 500) == 30.0
        assert rules.margin_rate(150, 0) == 0.0

    def test_cmp_mobile(self):
        # CMP : (10*100 + 10*300)/20 = 200
        assert rules.weighted_avg_cost(10, 100, 10, 300) == 200
        assert rules.weighted_avg_cost(0, 0, 5, 250) == 250

    def test_reappro(self):
        # besoin 20/j × (7 délai + 7 horizon) = 280 + sécu 50 - dispo 100 - attendu 30 = 200
        assert rules.reorder_quantity(20, 7, 50, 100, 30, 7) == 200
        assert rules.reorder_quantity(1, 1, 0, 1000, 0, 1) == 0

    def test_format_xof(self):
        assert rules.format_xof(150000) == "150 000 FCFA"
