#!/usr/bin/env python3
"""
Manual Champion Scraper

Allows running the champion data scraper locally for specific champions,
without needing to trigger the AWS Lambda function.

Usage:
    python manual_scraper.py champion1 champion2 ... [options]

Examples:
    python manual_scraper.py Aatrox Ahri
    python manual_scraper.py "K'Sante" Jinx --patch 15.5
    python manual_scraper.py --all  # Scrape all champions
    python manual_scraper.py --missing  # Scrape only missing champions

Options:
    --all           Scrape all champions
    --missing       Scrape only champions not in database
    --patch PATCH   Override patch version (default: latest)
    --dry-run       Show what would be scraped without actually doing it
    --help          Show this help message
"""

import os
import sys
import argparse
import json
import time
import random
from datetime import datetime

# Add scraper directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'scraper'))

from scraper.lolalytics_build_scraper import LolalyticsBuildScraper
from scraper.wiki_scraper import scrape_champion_abilities
from scraper.main import (
    check_patch_viability,
    normalize_patch_for_lolalytics,
    get_display_name,
    get_champion_id,
    get_champion_image_name,
    encode_champion_name_for_lolalytics,
    get_champion_list,
    get_current_patch
)

# Firebase imports (optional - will work without Firebase for testing)
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️ Firebase not available - running in offline mode")

class ManualScraper:
    """Manual champion scraper for local execution"""

    def __init__(self):
        self.db = None
        self.scraper = LolalyticsBuildScraper()

        # Initialize Firebase if available and credentials exist
        if FIREBASE_AVAILABLE:
            self._init_firebase()

    def _init_firebase(self):
        """Initialize Firebase connection"""
        try:
            if not firebase_admin._apps:
                # Try environment variable first (GitHub Actions/serverless)
                cred_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT_KEY')
                if cred_json:
                    cred = credentials.Certificate(json.loads(cred_json))
                else:
                    # Try local files
                    cred_paths = [
                        'firebase-key.json',
                        os.path.join(os.path.dirname(__file__), 'firebase-key.json'),
                        os.path.join(os.path.dirname(__file__), '..', 'firebase-key.json')
                    ]

                    cred = None
                    for path in cred_paths:
                        if os.path.exists(path):
                            cred = credentials.Certificate(path)
                            break

                    if not cred:
                        print("⚠️ No Firebase credentials found - running in offline mode")
                        return

                firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                print("✅ Firebase initialized")
        except Exception as e:
            print(f"⚠️ Firebase initialization failed: {e} - running in offline mode")

    def get_missing_champions(self):
        """Get champions that are not in the database"""
        if not self.db:
            print("❌ Cannot check missing champions without Firebase")
            return []

        try:
            # Get all champions from Riot API
            all_champions = get_champion_list()

            # Get champions already in database
            existing_champions = set()
            if self.db:
                champions_ref = self.db.collection('champions').document('data').collection('champions')
                existing_docs = champions_ref.stream()
                existing_champions = {doc.id for doc in existing_docs}

            # Find missing champions
            missing = [champ for champ in all_champions if champ not in existing_champions]

            print(f"Found {len(missing)} missing champions out of {len(all_champions)} total")
            return missing

        except Exception as e:
            print(f"❌ Error checking missing champions: {e}")
            return []

    def scrape_champion(self, champion_internal, target_patch=None, dry_run=False):
        """Scrape data for a single champion"""
        try:
            # Get champion display name
            champion_display = get_display_name(champion_internal)
            print(f"\n=== Processing {champion_internal} (display: {champion_display}) ===")

            if dry_run:
                print("🔍 DRY RUN: Would scrape champion data")
                return True

            # Scrape League Wiki abilities data
            print("📖 Scraping wiki abilities...")
            abilities_data = scrape_champion_abilities(champion_display)
            print(f"✅ Found {len(abilities_data)} abilities")

            # Scrape Lolalytics build data
            patch_to_use = target_patch or get_current_patch()
            print(f"📊 Scraping lolalytics data (patch {patch_to_use})...")
            normalized_patch = normalize_patch_for_lolalytics(patch_to_use)
            build_data = self.scraper.scrape_champion_build(champion_internal, patch=normalized_patch)

            # Get champion metadata
            champion_id = get_champion_id(champion_internal)
            champion_image_name = get_champion_image_name(champion_internal)

            # Combine the data
            combined_data = {
                'id': champion_internal,        # Internal champion name (like "KSante")
                'imageName': champion_image_name,
                'name': champion_display,
                'abilities': abilities_data
            }

            # Add lolalytics data if available
            if build_data:
                combined_data.update(build_data)
                print(f"✅ Combined data: {len(build_data.get('roles', {}))} roles")
            else:
                print("⚠️ No build data available")

            # Store in Firebase if available
            if self.db:
                self._store_champion_data(champion_internal, combined_data)

            return True

        except Exception as e:
            print(f"❌ Error processing {champion_internal}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _store_champion_data(self, champion_key, data):
        """Store champion data in Firebase"""
        try:
            doc_ref = self.db.collection('champions').document('data').collection('champions').document(champion_key)
            doc_ref.set(data)
            print(f"💾 Stored data for {champion_key}")
        except Exception as e:
            print(f"❌ Error storing data for {champion_key}: {e}")

    def update_role_containers(self):
        """Update role containers after manual scraping"""
        if not self.db:
            print("⚠️ Cannot update role containers without Firebase")
            return

        try:
            print("\n🔄 Updating role containers...")

            # Import the update function from lambda_function
            from lambda_function import update_role_containers
            update_role_containers()

        except Exception as e:
            print(f"❌ Error updating role containers: {e}")

def main():
    parser = argparse.ArgumentParser(
        description="Manual Champion Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument('champions', nargs='*', help='Champion names to scrape')
    parser.add_argument('--all', action='store_true', help='Scrape all champions')
    parser.add_argument('--missing', action='store_true', help='Scrape only missing champions')
    parser.add_argument('--patch', help='Override patch version')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be scraped without doing it')
    parser.add_argument('--update-roles', action='store_true', help='Update role containers after scraping')

    args = parser.parse_args()

    # Validate arguments
    if not args.champions and not args.all and not args.missing:
        print("❌ Error: Must specify champions, --all, or --missing")
        parser.print_help()
        sys.exit(1)

    if args.all and args.missing:
        print("❌ Error: Cannot use --all and --missing together")
        sys.exit(1)

    if args.champions and (args.all or args.missing):
        print("❌ Error: Cannot specify champions with --all or --missing")
        sys.exit(1)

    # Initialize scraper
    scraper = ManualScraper()

    # Determine which champions to scrape
    if args.all:
        champions_to_scrape = get_champion_list()
        print(f"📋 Will scrape all {len(champions_to_scrape)} champions")
    elif args.missing:
        champions_to_scrape = scraper.get_missing_champions()
        if not champions_to_scrape:
            print("ℹ️ No missing champions found")
            return
    else:
        # Use provided champion names - convert to internal keys
        champions_to_scrape = []
        all_champions = get_champion_list()

        for champ_input in args.champions:
            # Try to match input to champion
            matched = False
            for internal_key in all_champions:
                display_name = get_display_name(internal_key)
                if (champ_input.lower() == internal_key.lower() or
                    champ_input.lower() == display_name.lower() or
                    champ_input.lower() == encode_champion_name_for_lolalytics(display_name)):
                    champions_to_scrape.append(internal_key)
                    matched = True
                    break

            if not matched:
                print(f"⚠️ Champion '{champ_input}' not found, skipping")

        if not champions_to_scrape:
            print("❌ No valid champions specified")
            sys.exit(1)

    print(f"\n🚀 Starting manual scrape of {len(champions_to_scrape)} champions...")

    if args.dry_run:
        print("🔍 DRY RUN MODE - No actual scraping will be performed")

    # Scrape champions
    success_count = 0
    for i, champion in enumerate(champions_to_scrape):
        print(f"\n[{i+1}/{len(champions_to_scrape)}]")

        if scraper.scrape_champion(champion, args.patch, args.dry_run):
            success_count += 1

        # Rate limiting (skip for dry runs)
        if not args.dry_run and i < len(champions_to_scrape) - 1:
            wait_time = random.uniform(1, 3)
            print(f"⏱️ Waiting {wait_time:.1f}s...")
            time.sleep(wait_time)

    print(f"\n🎉 Manual scraping completed! {success_count}/{len(champions_to_scrape)} champions processed successfully")

    # Update role containers if requested
    if args.update_roles and not args.dry_run:
        scraper.update_role_containers()

if __name__ == "__main__":
    main()
