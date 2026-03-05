"""
Unit tests for data models.
Demonstrates the improved testability of the refactored code.
"""

import pytest
from datetime import datetime
from scraper.models import (
    ChampionAbility, RoleStats, CounterMatchup,
    ChampionRole, ChampionData, validate_champion_data
)


class TestChampionAbility:
    """Test ChampionAbility model"""

    def test_creation(self):
        ability = ChampionAbility(
            name="Flash",
            type="Q",
            cooldown="300/180/60",
            cost={"value": "50", "resource": "mana"}
        )
        assert ability.name == "Flash"
        assert ability.type == "Q"
        assert ability.cooldown == "300/180/60"
        assert ability.cost == {"value": "50", "resource": "mana"}

    def test_to_dict(self):
        ability = ChampionAbility(
            name="Ignite",
            type="Passive",
            cooldown="180",
            cost=None
        )
        data = ability.to_dict()
        assert data["name"] == "Ignite"
        assert data["type"] == "Passive"
        assert data["cooldown"] == "180"
        assert "cost" not in data  # None cost should not be included

    def test_from_dict(self):
        data = {
            "name": "Heal",
            "type": "W",
            "cooldown": "240",
            "cost": {"value": "70", "resource": "mana"}
        }
        ability = ChampionAbility.from_dict(data)
        assert ability.name == "Heal"
        assert ability.type == "W"
        assert ability.cooldown == "240"
        assert ability.cost == {"value": "70", "resource": "mana"}


class TestRoleStats:
    """Test RoleStats model"""

    def test_creation(self):
        stats = RoleStats(
            win_rate=52.3,
            pick_rate=15.7,
            games=12500,
            tier="A",
            rank=5,
            ban_rate=2.1
        )
        assert stats.win_rate == 52.3
        assert stats.pick_rate == 15.7
        assert stats.games == 12500
        assert stats.tier == "A"
        assert stats.rank == 5
        assert stats.ban_rate == 2.1

    def test_to_dict(self):
        stats = RoleStats(win_rate=48.5, pick_rate=12.3, games=8900)
        data = stats.to_dict()
        assert data["win_rate"] == 48.5
        assert data["pick_rate"] == 12.3
        assert data["games"] == 8900
        # Optional fields should not be included if None
        assert "tier" not in data
        assert "rank" not in data
        assert "ban_rate" not in data


class TestChampionData:
    """Test ChampionData model"""

    def test_creation(self):
        ability = ChampionAbility(name="Q", type="Q", cooldown="8/7/6/5/4")
        stats = RoleStats(win_rate=51.2, pick_rate=18.5, games=15000)
        role = ChampionRole(stats=stats, counters=[])

        champion = ChampionData(
            id="Ahri",
            imageName="Ahri",
            name="Ahri",
            abilities=[ability],
            roles={"middle": role},
            patch="15.5",
            lastUpdated=datetime.utcnow()
        )

        assert champion.id == "Ahri"
        assert champion.name == "Ahri"
        assert len(champion.abilities) == 1
        assert "middle" in champion.roles
        assert champion.patch == "15.5"

    def test_merge_scraped_data(self):
        # Existing champion data
        champion = ChampionData(
            id="Ahri",
            imageName="Ahri",
            name="Ahri",
            abilities=[],
            roles={}
        )

        # New scraped data
        scraped_data = {
            "abilities": [{"name": "Orb of Deception", "type": "Q", "cooldown": "7/6/5/4/3"}],
            "roles": {
                "middle": {
                    "stats": {"win_rate": 52.1, "pick_rate": 16.8, "games": 12000},
                    "counters": []
                }
            },
            "patch": "15.6"
        }

        merged = champion.merge_scraped_data(scraped_data)

        assert len(merged.abilities) == 1
        assert merged.abilities[0].name == "Orb of Deception"
        assert "middle" in merged.roles
        assert merged.patch == "15.6"
        assert merged.lastUpdated is not None


class TestValidation:
    """Test data validation functions"""

    def test_validate_champion_data_valid(self):
        data = {
            "id": "Ahri",
            "imageName": "Ahri",
            "name": "Ahri",
            "abilities": [
                {"name": "Q", "type": "Q", "cooldown": "8"}
            ],
            "roles": {
                "middle": {
                    "stats": {
                        "win_rate": 50.0,
                        "pick_rate": 15.0,
                        "games": 1000
                    }
                }
            }
        }
        assert validate_champion_data(data) == True

    def test_validate_champion_data_missing_required(self):
        data = {
            "name": "Ahri",  # Missing id, imageName
            "abilities": []
        }
        assert validate_champion_data(data) == False

    def test_validate_champion_data_invalid_stats(self):
        data = {
            "id": "Ahri",
            "imageName": "Ahri",
            "name": "Ahri",
            "abilities": [],
            "roles": {
                "middle": {
                    "stats": {
                        "win_rate": 150.0,  # Invalid: > 100
                        "pick_rate": 15.0,
                        "games": 1000
                    }
                }
            }
        }
        assert validate_champion_data(data) == False
