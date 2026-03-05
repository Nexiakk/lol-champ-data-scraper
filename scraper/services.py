"""
Service classes for the champion scraping system.
Breaks down the monolithic scraping function into focused, testable services.
"""

import time
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from .utils import (
    RiotAPIClient, ChampionNameMapper, PatchManager,
    get_display_name, get_champion_id, get_champion_image_name,
    get_champion_list, normalize_patch_for_lolalytics
)
from .turso_utils import TursoManager
from .logging_utils import get_logger, log_scraping_start, log_scraping_success, log_scraping_error, log_rate_limiting
from .config import get_config
from .models import ChampionData, ScrapingResult, ChampionAbility, ChampionRole, RoleStats, CounterMatchup
from .lolalytics_build_scraper import LolalyticsBuildScraper
from .wiki_scraper import scrape_champion_abilities


class ChampionScraper:
    """Service for scraping champion data from external sources"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger(__name__)
        self.lolalytics_scraper = LolalyticsBuildScraper()

    def scrape_champion_data(self, champion_internal: str, current_patch: str, target_patch: str, skip_wiki: bool = False) -> Dict:
        """
        Scrape all data for a single champion.
        
        Args:
            champion_internal: Internal champion key (e.g., 'Aatrox')
            current_patch: Current live patch (for wiki abilities - always current)
            target_patch: Target patch for lolalytics (may be fallback if current < 7 days old)
            skip_wiki: If True, skip wiki ability scraping (abilities already up to date globally)
        """
        log_scraping_start(champion_internal, "champion data scraping")

        try:
            # Get champion display name
            champion_display = get_display_name(champion_internal)

            # Scrape League Wiki abilities data - ONLY if not skipped
            # When skip_wiki is True, abilities are already up to date globally
            if skip_wiki:
                abilities_data = []  # Empty, won't be stored
                self.logger.info(f"Skipping wiki abilities for {champion_internal} - patch already up to date")
            else:
                # Scrape League Wiki abilities data - ALWAYS use current patch
                # Abilities are patch-specific and should be scraped immediately on day 1
                abilities_data = scrape_champion_abilities(champion_display)

            # Scrape Lolalytics build data - use target_patch (may be fallback)
            # Lolalytics data needs 7+ days of samples to be viable
            normalized_patch = normalize_patch_for_lolalytics(target_patch)
            build_data = self.lolalytics_scraper.scrape_champion_build(
                champion_internal,
                patch=normalized_patch
            )

            # Get champion metadata
            champion_id = get_champion_id(champion_internal)
            champion_image_name = get_champion_image_name(champion_internal)

            # Combine the data
            combined_data = {
                'id': champion_internal,
                'imageName': champion_image_name,
                'name': champion_display,
                'patch': target_patch,  # Lolalytics patch (may be different from abilities)
                'lastUpdated': datetime.utcnow()
            }

            # Only include abilities if we scraped them
            if not skip_wiki:
                combined_data['abilities'] = abilities_data
                combined_data['abilitiesPatch'] = current_patch  # Track which patch abilities belong to

            # Add lolalytics data if available
            if build_data:
                # Remove tier field since it's always diamond_plus
                build_data.pop('tier', None)
                combined_data.update(build_data)

            ability_count = len(abilities_data) if not skip_wiki else 0
            log_scraping_success(champion_internal, "champion data scraping",
                               f"{ability_count} abilities, {len(build_data.get('roles', {})) if build_data else 0} roles")
            return combined_data

        except Exception as e:
            log_scraping_error(champion_internal, "champion data scraping", e)
            raise

    def scrape_wiki_abilities_only(self, champion_internal: str, current_patch: str) -> Dict:
        """
        Scrape only wiki abilities data for a champion.
        Used for initial patch day when we want abilities immediately.
        """
        log_scraping_start(champion_internal, "wiki abilities scraping")

        try:
            champion_display = get_display_name(champion_internal)
            abilities_data = scrape_champion_abilities(champion_display)

            log_scraping_success(champion_internal, "wiki abilities scraping",
                               f"{len(abilities_data)} abilities")

            return {
                'abilities': abilities_data,
                'abilitiesPatch': current_patch,
                'abilitiesLastUpdated': datetime.utcnow()
            }

        except Exception as e:
            log_scraping_error(champion_internal, "wiki abilities scraping", e)
            raise

    def scrape_lolalytics_only(self, champion_internal: str, target_patch: str) -> Dict:
        """
        Scrape only lolalytics build data for a champion.
        Used for daily updates when abilities are already current.
        """
        log_scraping_start(champion_internal, "lolalytics data scraping")

        try:
            normalized_patch = normalize_patch_for_lolalytics(target_patch)
            build_data = self.lolalytics_scraper.scrape_champion_build(
                champion_internal,
                patch=normalized_patch
            )

            if build_data:
                build_data.pop('tier', None)

            log_scraping_success(champion_internal, "lolalytics data scraping",
                               f"{len(build_data.get('roles', {})) if build_data else 0} roles")

            return {
                'roles': build_data.get('roles', {}) if build_data else {},
                'patch': target_patch,
                'lastUpdated': datetime.utcnow()
            }

        except Exception as e:
            log_scraping_error(champion_internal, "lolalytics data scraping", e)
            raise


class DataProcessor:
    """Service for processing and validating scraped data"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger(__name__)

    def process_champion_data(self, raw_data: Dict) -> ChampionData:
        """Process raw scraped data into validated ChampionData model"""
        try:
            # Convert abilities
            abilities = []
            for ability_data in raw_data.get('abilities', []):
                ability = ChampionAbility(
                    name=ability_data.get('name', ''),
                    type=ability_data.get('type', ''),
                    cooldown=ability_data.get('cooldown', ''),
                    cost=ability_data.get('cost')
                )
                abilities.append(ability)

            # Convert roles
            roles = {}
            for role_name, role_data in raw_data.get('roles', {}).items():
                # Convert stats
                stats_data = role_data.get('stats', {})
                stats = RoleStats(
                    win_rate=stats_data.get('win_rate', 0.0),
                    pick_rate=stats_data.get('pick_rate', 0.0),
                    games=stats_data.get('games', 0),
                    tier=stats_data.get('tier'),
                    rank=stats_data.get('rank'),
                    ban_rate=stats_data.get('ban_rate')
                )

                # Convert counters
                counters = []
                for counter_data in role_data.get('counters', []):
                    counter = CounterMatchup(
                        champion=counter_data.get('champion', ''),
                        win_rate=counter_data.get('win_rate', 0.0),
                        games=counter_data.get('games')
                    )
                    counters.append(counter)

                roles[role_name] = ChampionRole(stats=stats, counters=counters)

            # Create ChampionData object
            champion_data = ChampionData(
                id=raw_data['id'],
                imageName=raw_data['imageName'],
                name=raw_data['name'],
                abilities=abilities,
                roles=roles,
                patch=raw_data.get('patch'),
                lastUpdated=raw_data.get('lastUpdated')
            )

            return champion_data

        except Exception as e:
            self.logger.error(f"Error processing champion data for {raw_data.get('id', 'unknown')}: {e}")
            raise

    def should_update_champion(self, current_data: Optional[Dict], new_data: Dict, current_patch: str = None) -> Dict:
        """
        Determine if and how a champion should be updated.
        
        Logic:
        - Abilities: Update only once per patch (tracked by abilitiesPatch field)
        - Lolalytics: Always update (stats grow daily with more samples)
        """
        # Get current patch from new_data if not provided
        if current_patch is None:
            current_patch = new_data.get('abilitiesPatch') or new_data.get('patch')
        
        # Check stored abilities patch
        stored_abilities_patch = current_data.get('abilitiesPatch') if current_data else None
        
        # Abilities should be updated if:
        # 1. No current data exists (first time)
        # 2. abilitiesPatch field doesn't exist (legacy data)
        # 3. abilitiesPatch is different from current patch (new patch)
        should_update_abilities = (
            not current_data or 
            not stored_abilities_patch or 
            stored_abilities_patch != current_patch
        )
        
        # Lolalytics should always update (growing sample size)
        # But we track if patch actually changed for logging
        lolalytics_patch_changed = (
            new_data.get('patch') != current_data.get('patch') if current_data else True
        )

        if should_update_abilities:
            return {
                'update': True,
                'abilities': True,
                'lolalytics': True,
                'reason': f"New patch: abilities_patch={current_patch}, lolalytics_patch={new_data.get('patch')}"
            }
        else:
            # Same abilities patch: only update lolalytics (growing sample)
            return {
                'update': True,  # Always update for lolalytics data
                'abilities': False,  # Skip abilities - already have current patch
                'lolalytics': True,  # Always update lolalytics (growing sample)
                'reason': f"Same abilities patch {stored_abilities_patch}: abilities=skip, lolalytics=always"
            }

    def _abilities_changed(self, old_abilities: List[Dict], new_abilities: List[Dict]) -> bool:
        """Check if abilities have changed (including cooldown values)"""
        if len(old_abilities) != len(new_abilities):
            return True

        # Compare each ability
        for old, new in zip(old_abilities, new_abilities):
            # Compare name
            if old.get('name') != new.get('name'):
                return True
            # Compare type (Q, W, E, R, Passive)
            if old.get('type') != new.get('type'):
                return True
            # Compare cooldown (crucial for balance changes like "reduced by 1 second")
            if old.get('cooldown') != new.get('cooldown'):
                return True
            # Compare cost if present
            old_cost = old.get('cost', {})
            new_cost = new.get('cost', {})
            if old_cost != new_cost:
                return True

        return False


class StorageService:
    """Service for storing champion data in Turso"""

    def __init__(self, turso_manager: TursoManager, config=None):
        self.turso = turso_manager
        self.config = config or get_config()
        self.logger = get_logger(__name__)

    def get_champion_data(self, champion_key: str) -> Optional[Dict]:
        """Get champion data from storage"""
        return self.turso.get_champion_data(champion_key)

    def store_champion_data(self, champion_key: str, data: Dict) -> bool:
        """Store champion data"""
        return self.turso.store_champion_data(champion_key, data)

    def update_role_containers(self, role_data: Dict) -> bool:
        """Update role container data"""
        return self.turso.update_role_containers(role_data)

    def cleanup_old_patches(self, current_patch: str) -> int:
        """Clean up old patch data"""
        return 0  # To be implemented for Turso cleanly if needed


class ScrapingOrchestrator:
    """Orchestrates the entire champion scraping process"""

    def __init__(self, config=None):
        self.config = config or get_config()
        self.logger = get_logger(__name__)

        # Initialize services
        from .turso_utils import TursoConfig
        self.turso_manager = TursoManager(TursoConfig())
        self.turso_available = self.turso_manager.initialize()

        if not self.turso_available:
            self.logger.warning("Turso not available - running in offline mode")

        self.scraper = ChampionScraper(self.config)
        self.processor = DataProcessor(self.config)
        self.storage = StorageService(self.turso_manager, self.config) if self.turso_available else None

    def scrape_and_store_champion(self, champion: str, target_patch: str, current_patch: str = None, skip_wiki: bool = False) -> ScrapingResult:
        """
        Scrape and store data for a single champion.
        
        Args:
            champion: Champion internal key (e.g., 'Aatrox')
            target_patch: Target patch for lolalytics data (may be fallback)
            current_patch: Current live patch for abilities (defaults to target_patch)
            skip_wiki: If True, skip wiki ability scraping (abilities already up to date globally)
        """
        try:
            # If current_patch not provided, use target_patch
            # This maintains backward compatibility
            if current_patch is None:
                current_patch = target_patch
            
            # Scrape data with both patches
            raw_data = self.scraper.scrape_champion_data(champion, current_patch, target_patch, skip_wiki)

            # Process data
            processed_data = self.processor.process_champion_data(raw_data)

            # Get current data for smart updates
            storage = self.storage
            current_data = storage.get_champion_data(champion) if storage else None

            # Determine update strategy - pass current_patch for abilities tracking
            update_decision = self.processor.should_update_champion(current_data, raw_data, current_patch)

            # Apply selective updates
            if update_decision['update']:
                final_data = self._apply_selective_updates(current_data or {}, raw_data, update_decision)

                # Store the data
                storage = self.storage
                if storage:
                    success = storage.store_champion_data(champion, final_data)
                    if not success:
                        raise Exception(f"Failed to store data for {champion}")
                    self.logger.info(f"✅ Successfully updated data for {champion}")
                else:
                    self.logger.info(f"✅ Extracted data for {champion} (offline mode - not stored)")
            else:
                self.logger.info(f"⏭️ Skipping update for {champion}")

            # Rate limiting
            self._apply_rate_limiting()

            return ScrapingResult(
                champion=champion,
                success=True,
                data=processed_data if update_decision['update'] else None
            )

        except Exception as e:
            self.logger.error(f"❌ Error processing {champion}: {e}")
            return ScrapingResult(
                champion=champion,
                success=False,
                error=str(e)
            )

    def update_role_containers(self):
        """Update role containers for optimized queries"""
        storage = self.storage
        if not storage:
            self.logger.warning("⚠️ Cannot update role containers without storage")
            return

        self.logger.info("Updating role containers for optimized queries...")

        try:
            # Get all champion data (simplified approach)
            all_champions = {}
            champions_list = get_champion_list()

            for champion_key in champions_list:
                data = storage.get_champion_data(champion_key)
                if data:
                    all_champions[champion_key] = data

            # Build role containers
            role_champions = {
                'top': [],
                'jungle': [],
                'middle': [],
                'bottom': [],
                'support': []
            }

            for champion_key, champ_data in all_champions.items():
                roles = champ_data.get('roles', {})
                for role in roles:
                    if role in role_champions:
                        role_champions[role].append({
                            'id': champion_key,
                            'name': champ_data.get('name', ''),
                            'pickRate': roles[role].get('stats', {}).get('pick_rate', 0)
                        })

            # Sort by pick rate
            for role in role_champions:
                role_champions[role].sort(key=lambda x: x['pickRate'], reverse=True)

            # Extract just champion IDs for storage
            role_data = {
                'roles': {role: [champ['id'] for champ in champions]
                         for role, champions in role_champions.items()},
                'lastUpdated': datetime.utcnow()
            }

            # Get current patch from first champion if available
            if all_champions:
                first_champion = next(iter(all_champions.values()))
                current_patch = first_champion.get('patch')
                if current_patch:
                    role_data['patch'] = current_patch

            # Store role data
            storage.update_role_containers(role_data)
            total_champions = sum(len(champs) for champs in role_champions.values())
            self.logger.info(f"✅ Updated role data: {total_champions} total champions")

        except Exception as e:
            self.logger.error(f"❌ Error updating role containers: {e}")

    def _apply_selective_updates(self, current_data: Dict, new_data: Dict, update_decision: Dict) -> Dict:
        """Apply selective updates based on decision"""
        final_data = current_data.copy() if current_data else {}

        if update_decision['abilities']:
            final_data['abilities'] = new_data.get('abilities', [])
            # Also update abilitiesPatch to track when abilities were last updated
            if 'abilitiesPatch' in new_data:
                final_data['abilitiesPatch'] = new_data['abilitiesPatch']
            if 'abilitiesLastUpdated' in new_data:
                final_data['abilitiesLastUpdated'] = new_data['abilitiesLastUpdated']

        if update_decision['lolalytics']:
            lolalytics_fields = ['patch', 'roles']
            for field in lolalytics_fields:
                if field in new_data:
                    final_data[field] = new_data[field]

        final_data['lastUpdated'] = datetime.utcnow()
        return final_data

    def _apply_rate_limiting(self):
        """Apply rate limiting between requests"""
        delay = random.uniform(
            self.config.scraping.rate_limit_delay,
            self.config.scraping.rate_limit_delay * 2
        )
        log_rate_limiting(delay)
        time.sleep(delay)
