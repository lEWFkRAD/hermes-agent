#!/usr/bin/env python
"""Quick validation script for NeonGrid grid bug fixes.

Run: python scripts/neongrid_review_checklist.py
"""
from sim.grid import Grid, TileType
from sim.unit import Unit, UnitClass, StatBlock, Faction
from sim.items import Weapon

def test_grid_bugs():
    """Verify all 6 grid bugs from the adversarial review are fixed."""
    g = Grid(width=15, height=11)
    g.set_tile_type(5, 5, TileType.WATER)

    # Bug 1: find_path validates start tile
    assert g.find_path((5, 5), (10, 5)) == [], "Bug 1: path from water should be []"

    # Bug 2: get_reachable_tiles validates start tile
    assert len(g.get_reachable_tiles((5, 5), 5)) == 0, "Bug 2: reachable from water should be 0"

    # Bug 3: get_attack_range validates start tile
    cls = UnitClass(name="Test", description="Test", base_stats=StatBlock())
    unit = Unit(id="test", name="Test", unit_class=cls, faction=Faction.PLAYER,
                x=5, y=5, stats=cls.base_stats, current_hp=20, current_pp=10)
    unit.equipped_weapon = Weapon("Test", "melee", "physical", min_range=1, max_range=1, base_damage=10)
    assert g.get_attack_range(unit) == [], "Bug 3: attack range from water should be []"

    # Bug 4: find_path returns [] for start == end
    assert g.find_path((0, 0), (0, 0)) == [], "Bug 4: path from tile to itself should be []"

    # Bug 5: place_unit clears old tile
    g2 = Grid(width=15, height=11)
    unit2 = Unit(id="test2", name="Test2", unit_class=cls, faction=Faction.PLAYER,
                 x=0, y=0, stats=cls.base_stats, current_hp=20, current_pp=10)
    g2.place_unit(unit2, 0, 0)
    g2.place_unit(unit2, 5, 5)
    assert g2.get_tile(0, 0).unit_id is None, "Bug 5: old tile should be cleared"

    # Bug 6: move_unit validates position
    unit3 = Unit(id="test3", name="Test3", unit_class=cls, faction=Faction.PLAYER,
                 x=0, y=0, stats=cls.base_stats, current_hp=20, current_pp=10)
    assert g2.move_unit(unit3, 100, 100) == False, "Bug 6: move to OOB should fail"

    unit4 = Unit(id="test4", name="Test4", unit_class=cls, faction=Faction.PLAYER,
                 x=100, y=100, stats=cls.base_stats, current_hp=20, current_pp=10)
    assert g2.move_unit(unit4, 5, 5) == False, "Bug 6b: move from OOB should fail"

    print("All 6 grid bug checks passed!")

if __name__ == "__main__":
    test_grid_bugs()
