"""
Refactored AWS Lambda function for champion data scraping.
Uses proper separation of concerns and modern Python practices.
"""

import os
import json
import time
import random
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime

# Import refactored utilities
from scraper.utils import (
    RiotAPIClient, ChampionNameMapper, PatchManager,
    get_display_name, get_champion_id, get_champion_image_name,
    get_champion_list, normalize_patch_for_lolalytics
)
from scraper.turso_utils import TursoManager, TursoConfig
from scraper.logging_utils import get_logger, log_scraping_start, log_scraping_success, log_scraping_error
from scraper.config import get_config
from scraper.models import ChampionData, ScrapingResult, RoleContainer
from scraper.lolalytics_build_scraper import LolalyticsBuildScraper
from scraper.wiki_scraper import scrape_champion_abilities
from scraper.services import ScrapingOrchestrator

# Legacy import for backward compatibility
from scraper.main_legacy import check_patch_viability

# Global instances
_turso_manager: Optional[TursoManager] = None
_logger = get_logger(__name__)

def lambda_handler(event, context):
    """AWS Lambda handler function (kept for compatibility)"""
    try:
        result = scrape_and_store_data()
        return {
            'statusCode': 200,
            'body': json.dumps(result)
        }
    except Exception as e:
        _logger.error(f"Critical error in lambda_handler: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'Error: {str(e)}')
        }

def scrape_and_store_data():
    """Main function to scrape data and store in Firebase using service-based architecture"""
    _logger.info("Starting data scraping with service-based architecture...")

    # Get current patch and check viability
    try:
        riot_client = RiotAPIClient()
        current_patch = riot_client.get_current_patch()
    except Exception as e:
        _logger.error(f"Error fetching current patch: {e}")
        current_patch = "15.24"  # Fallback

    _logger.info(f"Current patch: {current_patch}")

    # Check if current patch has sufficient sample size for lolalytics
    use_current, target_patch, viability_metrics = check_patch_viability(current_patch)

    if use_current:
        _logger.info(f"✅ Using current patch {current_patch} for scraping")
    else:
        _logger.warning(f"⚠️ Current patch {current_patch} has insufficient lolalytics data (< 7 days)")
        _logger.info(f"🔄 Falling back to patch {target_patch} for lolalytics")
        _logger.info(f"📋 Wiki abilities will still use current patch {current_patch}")

    # Initialize orchestrator
    orchestrator = ScrapingOrchestrator()

    # Check global patch info to see if wiki abilities are already up to date
    skip_wiki = False
    if orchestrator.turso_available:
        try:
            global_patch_info = orchestrator.turso_manager.get_global_patch_info()
            if global_patch_info and global_patch_info.get('abilitiesPatch') == current_patch:
                skip_wiki = True
                _logger.info(f"⏭️ Global abilities patch already up to date ({current_patch}) - skipping wiki scraping for all champions")
            else:
                stored_patch = global_patch_info.get('abilitiesPatch') if global_patch_info else None
                _logger.info(f"🔄 Wiki abilities need update: stored={stored_patch}, current={current_patch}")
        except Exception as e:
            _logger.warning(f"Could not check global patch info: {e}")
    else:
        _logger.warning("Turso not available - cannot check global patch info, will scrape wiki for all champions")

    # Get champions to process
    champions = get_champion_list()
    _logger.info(f"Processing {len(champions)} champions")

    success_count = 0
    error_count = 0

    # Process each champion using the orchestrator
    # Pass both current_patch (for wiki abilities) and target_patch (for lolalytics)
    for i, champion in enumerate(champions):
        _logger.info(f"Processing champion {i+1}/{len(champions)}: {champion}")

        try:
            result = orchestrator.scrape_and_store_champion(champion, target_patch, current_patch, skip_wiki)

            if result.success:
                success_count += 1
            else:
                error_count += 1
                _logger.error(f"Failed to process {champion}: {result.error}")
        except Exception as e:
            error_count += 1
            _logger.error(f"❌ Critical error processing {champion}: {e}")
            import traceback
            _logger.error(traceback.format_exc())
            # Continue to next champion instead of crashing

    # Update global patch info if we scraped wiki abilities (i.e., didn't skip)
    if orchestrator.turso_available and not skip_wiki:
        try:
            orchestrator.turso_manager.update_global_patch_info(current_patch)
            _logger.info(f"✅ Updated global abilities patch to {current_patch}")
        except Exception as e:
            _logger.error(f"❌ Failed to update global patch info: {e}")
    elif skip_wiki:
        _logger.info("⏭️ Skipped wiki scraping - global patch info unchanged")

    # Update role containers for optimized queries (only if Turso is available)
    if orchestrator.turso_available:
        _logger.info("Updating role containers...")
        orchestrator.update_role_containers()

        # Clean up old patch data only if we switched patches
        if target_patch != current_patch:
            _logger.info("Patch changed - cleaning up old patch data...")
            cleanup_old_patch_data()
        else:
            _logger.info("Same patch - skipping cleanup")
    else:
        _logger.warning("Skipping role container updates - Turso not available")

    _logger.info(f"🎉 Data scraping completed! {success_count} successes, {error_count} errors")

    # Create summary for GitHub Actions
    summary = {
        "success": True,
        "total_champions": len(champions),
        "success_count": success_count,
        "error_count": error_count,
        "turso_available": orchestrator.turso_available,
        "current_patch": current_patch,
        "target_patch": target_patch
    }

    # Write summary to file for GitHub Actions
    import json
    with open("scrape_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    return summary

class SmartUpdateEngine:
    """Simplified update system - patch viability already checked globally"""

    def should_update_champion(self, current_data, new_data):
        """Simplified: Patch viability already checked globally"""

        # Always update on patch changes (patch already validated globally as ready)
        if new_data.get('patch') != current_data.get('patch'):
            return {
                'update': True,
                'abilities': True,
                'lolalytics': True,
                'reason': f"Patch changed to {new_data['patch']} (validated globally)"
            }

        # Same patch: Only update if abilities changed
        else:
            abilities_changed = self._abilities_changed(
                current_data.get('abilities', []),
                new_data.get('abilities', [])
            )
            return {
                'update': abilities_changed,  # Only if abilities changed
                'abilities': abilities_changed,
                'lolalytics': True,  # Always update (growing sample)
                'reason': f"Same patch: abilities={abilities_changed}, lolalytics=True"
            }

    def _abilities_changed(self, old_abilities, new_abilities):
        """Check if abilities actually changed"""
        if len(old_abilities) != len(new_abilities):
            return True

        # Compare each ability
        for old, new in zip(old_abilities, new_abilities):
            if (old.get('name') != new.get('name') or
                old.get('cooldown') != new.get('cooldown') or
                old.get('type') != new.get('type')):
                return True

        return False

    def get_viable_roles(self, scraped_data, historical_roles=None):
        """Get all roles that should be stored - simplified since we only scrape ≥9% roles"""
        viable_roles = set()

        # All scraped roles are already ≥9% pickrate, so just return them
        viable_roles.update(scraped_data.get('roles', {}).keys())

        # Add historically viable roles (if any exist from before the optimization)
        if historical_roles:
            viable_roles.update(historical_roles)

        return list(viable_roles)

def get_turso_manager() -> TursoManager:
    """Get or create Turso manager instance"""
    global _turso_manager
    if _turso_manager is None:
        config = get_config()
        from scraper.turso_utils import TursoConfig
        _turso_manager = TursoManager(TursoConfig())
        _turso_manager.initialize()
    return _turso_manager

def get_current_champion_data(champion_key: str) -> Dict:
    """Get current champion data from Turso"""
    turso_mgr = get_turso_manager()
    return turso_mgr.get_champion_data(champion_key) or {}

def store_combined_champion_data_smart(champion: str, current_data: Dict, new_data: Dict, update_decision: Dict):
    """Store combined champion data using smart update decisions"""
    turso_mgr = get_turso_manager()

    # Start with current data or empty dict
    final_data = current_data.copy() if current_data else {}

    # Apply selective updates based on decision
    if update_decision['abilities']:
        final_data['abilities'] = new_data.get('abilities', [])

    if update_decision['lolalytics']:
        # Update with new build data (exclude tier field)
        lolalytics_fields = ['patch', 'roles']
        for field in lolalytics_fields:
            if field in new_data:
                final_data[field] = new_data[field]

        # Filter to viable roles only
        if 'roles' in final_data:
            update_engine = SmartUpdateEngine()
            viable_roles = update_engine.get_viable_roles(new_data)
            final_data['roles'] = {
                role: final_data['roles'][role]
                for role in viable_roles
                if role in final_data['roles']
            }

    # Store the updated data
    success = turso_mgr.store_champion_data(champion, final_data)
    if not success:
        raise Exception(f"Failed to store data for {champion}")

def update_role_containers():
    """Update role containers for optimized queries"""
    turso_mgr = get_turso_manager()

    _logger.info("Updating role containers for new structure...")

    try:
        # This is a complex operation that would need to be restructured
        # For now, keep the existing logic but use FirebaseManager
        # TODO: Refactor this to use proper data structures and models

        # For backward compatibility, we'll implement a simplified version
        # that uses the TursoManager methods

        # Get all champion data (this is inefficient but works for now)
        all_champions = {}
        champions_list = get_champion_list()

        for champion_key in champions_list:
            data = turso_mgr.get_champion_data(champion_key)
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
        turso_mgr.update_role_containers(role_data)
        total_champions = sum(len(champs) for champs in role_champions.values())
        _logger.info(f"✅ Updated role data: {total_champions} total champions")

    except Exception as e:
        _logger.error(f"❌ Error updating role containers: {e}")

def cleanup_old_patch_data():
    """Clean up old patch data, keeping only recent patches"""
    turso_mgr = get_turso_manager()

    _logger.info("🧹 Cleaning up old patch data...")

    try:
        # Get current patch from a sample champion
        current_patch = None
        # This is complex to implement efficiently with TursoManager
        # For now, skip this cleanup in the refactored version
        # TODO: Implement proper cleanup using TursoManager
        _logger.info("⚠️ Cleanup skipped in refactored version - needs implementation")

    except Exception as e:
        _logger.error(f"❌ Error during cleanup: {e}")

# Main execution block for running as standalone script (GitHub Actions)
if __name__ == "__main__":
    try:
        scrape_and_store_data()
        print("✅ Champion scraping completed successfully!")
    except Exception as e:
        print(f"❌ Error during scraping: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
