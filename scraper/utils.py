"""
Shared utilities for the champion scraping system.
Contains common functions used across different scraper modules.
"""

import os
import json
import time
import requests
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote
import re


class RiotAPIClient:
    """Client for Riot Games API with caching"""

    def __init__(self, cache_timeout: int = 3600):
        self.cache_timeout = cache_timeout
        self.cache = {}

    def _get_cached(self, key: str) -> Optional[Dict]:
        """Get cached data if still valid"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_timeout:
                return data
            else:
                del self.cache[key]
        return None

    def _set_cached(self, key: str, data: Dict):
        """Cache data with timestamp"""
        self.cache[key] = (data, time.time())

    def get_versions(self) -> List[str]:
        """Get all League of Legends patch versions"""
        cached = self._get_cached("versions")
        if cached:
            return cached

        try:
            response = requests.get("https://ddragon.leagueoflegends.com/api/versions.json", timeout=10)
            response.raise_for_status()
            versions = response.json()
            self._set_cached("versions", versions)
            return versions
        except Exception as e:
            print(f"Error fetching versions: {e}")
            return []

    def get_current_patch(self) -> str:
        """Get the current patch version"""
        versions = self.get_versions()
        return versions[0] if versions else "15.24"

    def get_champion_data(self, patch: Optional[str] = None) -> Dict:
        """Get champion data mapping"""
        cache_key = f"champion_data_{patch or 'latest'}"
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        patch_to_use = patch or self.get_current_patch()

        try:
            url = f"https://ddragon.leagueoflegends.com/cdn/{patch_to_use}/data/en_US/champion.json"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            self._set_cached(cache_key, data)
            return data
        except Exception as e:
            print(f"Error fetching champion data: {e}")
            return {}


class ChampionNameMapper:
    """Handles champion name mapping and encoding"""

    def __init__(self, riot_client: RiotAPIClient):
        self.riot_client = riot_client
        self._mapping_cache = {}
        self._lolalytics_to_internal_cache = {}

    def _get_mapping(self) -> Dict[str, Dict]:
        """Get comprehensive champion mapping"""
        if self._mapping_cache:
            return self._mapping_cache

        data = self.riot_client.get_champion_data()
        mapping = {}

        for key, champ_data in data.get('data', {}).items():
            mapping[key] = {
                'id': int(champ_data['key']),
                'imageName': key,
                'name': champ_data['name'],
                'internalKey': key
            }

        self._mapping_cache = mapping
        return mapping

    def _build_lolalytics_to_internal_mapping(self) -> Dict[str, str]:
        """Build a mapping from lolalytics-format names to internal champion keys"""
        if self._lolalytics_to_internal_cache:
            return self._lolalytics_to_internal_cache

        mapping = {}
        for internal_key in self.get_champion_list():
            # Convert internal key to lolalytics format
            lolalytics_key = self.encode_for_lolalytics(self.get_display_name(internal_key))
            mapping[lolalytics_key] = internal_key

        self._lolalytics_to_internal_cache = mapping
        return mapping

    def get_internal_key_from_lolalytics(self, lolalytics_name: str) -> Optional[str]:
        """
        Convert a lolalytics-format champion name to internal champion key.
        
        Args:
            lolalytics_name: Champion name in lolalytics format (e.g., 'leesin', 'xinzhao', 'missfortune')
            
        Returns:
            Internal champion key (e.g., 'LeeSin', 'XinZhao', 'MissFortune') or None if not found
        """
        # Normalize the input: lowercase and remove spaces/hyphens
        normalized = lolalytics_name.lower().replace('-', '').replace(' ', '').replace("'", '').replace('"', '')

        # Handle special case: Monkey King is "wukong" on lolalytics
        if normalized == 'monkeyking':
            normalized = 'wukong'

        # Build and use the reverse mapping
        lolalytics_map = self._build_lolalytics_to_internal_mapping()
        return lolalytics_map.get(normalized)

    def get_display_name(self, internal_key: str) -> str:
        """Convert internal key to display name"""
        mapping = self._get_mapping()
        return mapping.get(internal_key, {}).get('name', internal_key)

    def get_champion_id(self, internal_key: str) -> Optional[int]:
        """Get numeric champion ID"""
        mapping = self._get_mapping()
        return mapping.get(internal_key, {}).get('id')

    def get_image_name(self, internal_key: str) -> str:
        """Get image name for champion"""
        mapping = self._get_mapping()
        return mapping.get(internal_key, {}).get('imageName', internal_key)

    def get_champion_list(self) -> List[str]:
        """Get sorted list of all champion internal keys"""
        mapping = self._get_mapping()
        champions = list(mapping.keys())
        champions.sort()
        return champions

    def encode_for_wiki(self, display_name: str) -> str:
        """Encode champion name for League Wiki URL"""
        encoded = display_name.replace(' ', '_')
        return quote(encoded, safe='_')

    def encode_for_lolalytics(self, display_name: str) -> str:
        """Encode champion name for Lolalytics URL"""
        encoded = display_name.lower()
        encoded = re.sub(r"['\"]", '', encoded)
        encoded = encoded.replace(' ', '')

        # Special case for Monkey King
        if encoded == 'monkeyking':
            return 'wukong'

        return encoded


class PatchManager:
    """Manages patch-related operations"""

    def __init__(self, riot_client: RiotAPIClient):
        self.riot_client = riot_client

    def normalize_patch_for_lolalytics(self, patch_version: str) -> str:
        """Convert Riot format (x.y.z) to Lolalytics format (x.y)"""
        parts = patch_version.split('.')
        return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else patch_version

    def get_previous_patch(self, current_patch: str) -> Optional[str]:
        """Find the previous patch version"""
        versions = self.riot_client.get_versions()

        try:
            current_index = versions.index(current_patch)
            if current_index + 1 < len(versions):
                return versions[current_index + 1]  # List is newest first
        except ValueError:
            pass

        return None


# Global instances for backward compatibility
_riot_client = RiotAPIClient()
_name_mapper = ChampionNameMapper(_riot_client)
_patch_manager = PatchManager(_riot_client)

# Export functions for backward compatibility
def get_display_name(internal_key: str) -> str:
    return _name_mapper.get_display_name(internal_key)

def get_champion_id(internal_key: str) -> Optional[int]:
    return _name_mapper.get_champion_id(internal_key)

def get_champion_image_name(internal_key: str) -> str:
    return _name_mapper.get_image_name(internal_key)

def get_champion_list() -> List[str]:
    return _name_mapper.get_champion_list()

def encode_champion_name_for_wiki(display_name: str) -> str:
    return _name_mapper.encode_for_wiki(display_name)

def encode_champion_name_for_lolalytics(display_name: str) -> str:
    return _name_mapper.encode_for_lolalytics(display_name)

def get_current_patch() -> str:
    return _riot_client.get_current_patch()

def normalize_patch_for_lolalytics(patch_version: str) -> str:
    return _patch_manager.normalize_patch_for_lolalytics(patch_version)

def get_previous_patch(current_patch: str) -> Optional[str]:
    return _patch_manager.get_previous_patch(current_patch)

def get_internal_key_from_lolalytics(lolalytics_name: str) -> Optional[str]:
    """Convert a lolalytics-format champion name to internal champion key."""
    return _name_mapper.get_internal_key_from_lolalytics(lolalytics_name)
