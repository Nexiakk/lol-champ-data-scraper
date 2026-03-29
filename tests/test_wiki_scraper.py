"""
Unit tests for the wiki scraper with form detection.
"""
import unittest
import os
from bs4 import BeautifulSoup
from scraper.wiki_scraper import (
    detect_forms,
    extract_all_abilities,
    group_abilities_by_form,
    scrape_champion_abilities_from_html,
    extract_cooldown,
    extract_cost,
    extract_ability_name,
    extract_skill_type,
    clean_cooldown,
    extract_icon_url,
    extract_description
)


class TestFormDetection(unittest.TestCase):
    """Test form detection for multi-form champions."""

    def setUp(self):
        """Load test fixtures."""
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')
        self.champions = {}

        for champ in ['Jayce', 'Elise', 'Nidalee', 'Aatrox', 'Yasuo']:
            fixture_path = os.path.join(self.fixtures_dir, f'{champ.lower()}.html')
            if os.path.exists(fixture_path):
                with open(fixture_path, 'r', encoding='utf-8') as f:
                    self.champions[champ] = BeautifulSoup(f.read(), 'html.parser')

    def test_detect_forms_jayce(self):
        """Jayce should have 2 forms: Mercury Hammer and Mercury Cannon."""
        soup = self.champions['Jayce']
        forms = detect_forms(soup, 'Jayce')

        self.assertEqual(len(forms), 2)
        self.assertEqual(forms[0]['name'], 'Mercury Hammer')
        self.assertEqual(forms[0]['key'], 'hammer')
        self.assertEqual(forms[1]['name'], 'Mercury Cannon')
        self.assertEqual(forms[1]['key'], 'cannon')

    def test_detect_forms_elise(self):
        """Elise should have 2 forms: Human Form and Spider Form."""
        soup = self.champions['Elise']
        forms = detect_forms(soup, 'Elise')

        self.assertEqual(len(forms), 2)
        self.assertEqual(forms[0]['name'], 'Human Form')
        self.assertEqual(forms[0]['key'], 'human')
        self.assertEqual(forms[1]['name'], 'Spider Form')
        self.assertEqual(forms[1]['key'], 'spider')

    def test_detect_forms_nidalee(self):
        """Nidalee should have 2 forms: Human Form and Cougar Form."""
        soup = self.champions['Nidalee']
        forms = detect_forms(soup, 'Nidalee')

        self.assertEqual(len(forms), 2)
        self.assertEqual(forms[0]['name'], 'Human Form')
        self.assertEqual(forms[1]['name'], 'Cougar Form')

    def test_detect_forms_single_form(self):
        """Single form champions should have 0 forms detected."""
        for champ in ['Aatrox', 'Yasuo']:
            soup = self.champions[champ]
            forms = detect_forms(soup, champ)
            self.assertEqual(len(forms), 0, f"{champ} should have 0 forms")


class TestAbilityExtraction(unittest.TestCase):
    """Test ability data extraction."""

    def setUp(self):
        """Load test fixtures."""
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')
        self.champions = {}

        for champ in ['Jayce', 'Elise', 'Aatrox']:
            fixture_path = os.path.join(self.fixtures_dir, f'{champ.lower()}.html')
            if os.path.exists(fixture_path):
                with open(fixture_path, 'r', encoding='utf-8') as f:
                    self.champions[champ] = BeautifulSoup(f.read(), 'html.parser')

    def test_extract_abilities_jayce(self):
        """Jayce should have multiple abilities including cooldowns."""
        soup = self.champions['Jayce']
        abilities = extract_all_abilities(soup, 'Jayce')

        # Should have at least 8 abilities (2 forms x 4 abilities each)
        self.assertGreaterEqual(len(abilities), 8)

        # Check for specific abilities
        ability_names = [a['name'] for a in abilities]
        self.assertIn('To the Skies!', ability_names)
        self.assertIn('Shock Blast', ability_names)
        self.assertIn('Transform Mercury Cannon', ability_names)

    def test_extract_cooldowns(self):
        """Should extract cooldown strings properly."""
        soup = self.champions['Jayce']
        abilities = extract_all_abilities(soup, 'Jayce')

        # Find an ability with cooldown
        ability_with_cd = next((a for a in abilities if a.get('cooldown')), None)
        self.assertIsNotNone(ability_with_cd)

        # Check cooldown format
        cooldown = ability_with_cd['cooldown']
        self.assertIsInstance(cooldown, str)
        # Should contain numbers
        self.assertTrue(any(c.isdigit() for c in cooldown))

    def test_extract_costs(self):
        """Should extract mana/energy costs."""
        soup = self.champions['Jayce']
        abilities = extract_all_abilities(soup, 'Jayce')

        # Find an ability with cost
        ability_with_cost = next((a for a in abilities if a.get('cost')), None)
        if ability_with_cost:
            cost = ability_with_cost['cost']
            self.assertIn('value', cost)
            self.assertIn('resource', cost)
            self.assertIn(cost['resource'], ['mana', 'energy', 'fury', 'health'])

    def test_extract_passives(self):
        """Should extract passive abilities."""
        soup = self.champions['Aatrox']
        abilities = extract_all_abilities(soup, 'Aatrox')

        passive_abilities = [a for a in abilities if a['type'] == 'Passive']
        self.assertGreaterEqual(len(passive_abilities), 1)

        # Check for Aatrox passive
        ability_names = [a['name'] for a in abilities]
        self.assertIn('Deathbringer Stance', ability_names)


class TestFormGrouping(unittest.TestCase):
    """Test ability grouping by form."""

    def test_group_single_form(self):
        """Single form should put all abilities in one group."""
        abilities = [
            {'name': 'Passive', 'type': 'Passive'},
            {'name': 'Q Ability', 'type': 'Q'},
            {'name': 'W Ability', 'type': 'W'},
            {'name': 'E Ability', 'type': 'E'},
            {'name': 'R Ability', 'type': 'R'},
        ]
        forms = [{'name': 'Skills', 'key': 'default'}]

        result = group_abilities_by_form(abilities, forms)

        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]['abilities']), 5)

    def test_group_multi_form(self):
        """Multi-form should split abilities across forms."""
        abilities = [
            {'name': 'Passive 1', 'type': 'Passive'},
            {'name': 'Q1', 'type': 'Q'},
            {'name': 'W1', 'type': 'W'},
            {'name': 'E1', 'type': 'E'},
            {'name': 'R1', 'type': 'R'},
            {'name': 'Q2', 'type': 'Q'},
            {'name': 'W2', 'type': 'W'},
            {'name': 'E2', 'type': 'E'},
            {'name': 'R2', 'type': 'R'},
        ]
        forms = [
            {'name': 'Form 1', 'key': 'form1'},
            {'name': 'Form 2', 'key': 'form2'}
        ]

        result = group_abilities_by_form(abilities, forms)

        self.assertEqual(len(result), 2)
        # Abilities should be split between forms (4 or 5 per form depending on total)
        total_abilities = sum(len(form['abilities']) for form in result)
        self.assertEqual(total_abilities, 9)
        # Form 1 and Form 2 should have abilities
        self.assertGreater(len(result[0]['abilities']), 0)
        self.assertGreater(len(result[1]['abilities']), 0)


class TestFullScraping(unittest.TestCase):
    """Test complete scraping pipeline."""

    def setUp(self):
        """Load test fixtures."""
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')

    def test_scrape_jayce(self):
        """Full scrape of Jayce should produce correct structure."""
        fixture_path = os.path.join(self.fixtures_dir, 'jayce.html')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            html = f.read()

        result = scrape_champion_abilities_from_html(html, 'Jayce')

        self.assertTrue(result['hasMultipleForms'])
        self.assertEqual(len(result['forms']), 2)

        # Check Mercury Hammer form
        hammer_form = result['forms'][0]
        self.assertEqual(hammer_form['name'], 'Mercury Hammer')
        hammer_ability_names = [a['name'] for a in hammer_form['abilities']]
        self.assertIn('To the Skies!', hammer_ability_names)
        self.assertIn('Transform Mercury Cannon', hammer_ability_names)

        # Check Mercury Cannon form
        cannon_form = result['forms'][1]
        self.assertEqual(cannon_form['name'], 'Mercury Cannon')
        cannon_ability_names = [a['name'] for a in cannon_form['abilities']]
        self.assertIn('Shock Blast', cannon_ability_names)
        self.assertIn('Acceleration Gate', cannon_ability_names)

    def test_scrape_single_form(self):
        """Full scrape of single form champion."""
        fixture_path = os.path.join(self.fixtures_dir, 'aatrox.html')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            html = f.read()

        result = scrape_champion_abilities_from_html(html, 'Aatrox')

        self.assertFalse(result['hasMultipleForms'])
        self.assertEqual(len(result['forms']), 1)

        abilities = result['forms'][0]['abilities']
        self.assertEqual(len(abilities), 5)  # P, Q, W, E, R

        # Check ability types
        types = [a['type'] for a in abilities]
        self.assertIn('Passive', types)
        self.assertIn('Q', types)
        self.assertIn('W', types)
        self.assertIn('E', types)
        self.assertIn('R', types)


class TestCooldownDisplay(unittest.TestCase):
    """Test that cooldowns are properly extracted for display."""

    def test_cooldown_with_levels(self):
        """Should extract full cooldown string with level scaling."""
        html = '''
        <div class="skill_q">
            <div class="ability-info-stats__stat">
                <div class="ability-info-stats__stat-label">Cooldown:</div>
                <div class="ability-info-stats__stat-value">10 / 9 / 8 / 7 / 6</div>
            </div>
        </div>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        skill_div = soup.find('div', class_='skill_q')
        cooldown = extract_cooldown(skill_div)

        self.assertEqual(cooldown, '10/9/8/7/6')

    def test_no_cooldown_for_passive(self):
        """Passives may not have cooldown - should return None."""
        html = '''
        <div class="skill_innate">
            <div class="ability-info-stats__ability">Some Passive</div>
        </div>
        '''
        soup = BeautifulSoup(html, 'html.parser')
        skill_div = soup.find('div', class_='skill_innate')
        cooldown = extract_cooldown(skill_div)

        self.assertIsNone(cooldown)


class TestCleanCooldown(unittest.TestCase):
    """Test cooldown cleaning and standardization."""

    def test_remove_parenthetical_annotations(self):
        """Should remove parenthetical annotations like (based on level)."""
        self.assertEqual(clean_cooldown('22 – 8.59(based on level)'), '22 – 8.59')
        self.assertEqual(clean_cooldown('4 – 1.33(based onbonusattack speed)'), '4 – 1.33')
        self.assertEqual(clean_cooldown('10(something)'), '10')

    def test_standardize_slash_spacing(self):
        """Should standardize spacing around / separators."""
        self.assertEqual(clean_cooldown('14 / 12 / 10 / 8 / 6'), '14/12/10/8/6')
        self.assertEqual(clean_cooldown('13 / 11.4/ 9.8/ 8.2/ 6.6/ 5'), '13/11.4/9.8/8.2/6.6/5')
        self.assertEqual(clean_cooldown('0.5/ 0.4/ 0.3/ 0.2/ 0.1'), '0.5/0.4/0.3/0.2/0.1')
        self.assertEqual(clean_cooldown('10 / 9 / 8 / 7 / 6'), '10/9/8/7/6')

    def test_preserve_range_formats(self):
        """Should preserve range formats like X – Y."""
        self.assertEqual(clean_cooldown('22 – 8.59'), '22 – 8.59')
        self.assertEqual(clean_cooldown('4 – 1.33'), '4 – 1.33')

    def test_combined_cleaning(self):
        """Should handle combined issues."""
        self.assertEqual(clean_cooldown('22 – 8.59(based on level)'), '22 – 8.59')
        self.assertEqual(clean_cooldown('4 – 1.33(based onbonusattack speed)'), '4 – 1.33')
        self.assertEqual(clean_cooldown('14 / 12 / 10 / 8 / 6'), '14/12/10/8/6')

    def test_clean_strings(self):
        """Should pass through already clean strings."""
        self.assertEqual(clean_cooldown('10/9/8/7/6'), '10/9/8/7/6')
        self.assertEqual(clean_cooldown('22 – 8.59'), '22 – 8.59')
        self.assertEqual(clean_cooldown('120/100/80'), '120/100/80')


class TestCooldownCleaningIntegration(unittest.TestCase):
    """Test that cooldown cleaning is properly integrated."""

    def setUp(self):
        """Load test fixtures."""
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')

    def test_aatrox_passive_cooldown(self):
        """Aatrox passive should have cleaned cooldown."""
        fixture_path = os.path.join(self.fixtures_dir, 'aatrox.html')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            html = f.read()

        result = scrape_champion_abilities_from_html(html, 'Aatrox')
        passive = next((a for a in result['forms'][0]['abilities'] if a['type'] == 'Passive'), None)
        
        self.assertIsNotNone(passive)
        self.assertEqual(passive['cooldown'], '22 – 8.59')
        self.assertNotIn('(based on level)', passive['cooldown'])

    def test_yasuo_q_cooldown(self):
        """Yasuo Q should have cleaned cooldown."""
        fixture_path = os.path.join(self.fixtures_dir, 'yasuo.html')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            html = f.read()

        result = scrape_champion_abilities_from_html(html, 'Yasuo')
        q_ability = next((a for a in result['forms'][0]['abilities'] if a['type'] == 'Q'), None)
        
        self.assertIsNotNone(q_ability)
        self.assertEqual(q_ability['cooldown'], '4 – 1.33')
        self.assertNotIn('(based onbonusattack speed)', q_ability['cooldown'])

    def test_standard_cooldown_formatting(self):
        """Standard cooldowns should have no spaces around slashes."""
        fixture_path = os.path.join(self.fixtures_dir, 'aatrox.html')
        with open(fixture_path, 'r', encoding='utf-8') as f:
            html = f.read()

        result = scrape_champion_abilities_from_html(html, 'Aatrox')
        q_ability = next((a for a in result['forms'][0]['abilities'] if a['type'] == 'Q'), None)
        
        self.assertIsNotNone(q_ability)
        self.assertEqual(q_ability['cooldown'], '14/12/10/8/6')


class TestIconAndDescriptionExtraction(unittest.TestCase):
    """Test icon URL and description extraction."""

    def setUp(self):
        """Load test fixtures."""
        self.fixtures_dir = os.path.join(os.path.dirname(__file__), 'fixtures')
        self.champions = {}

        for champ in ['Jayce', 'Aatrox']:
            fixture_path = os.path.join(self.fixtures_dir, f'{champ.lower()}.html')
            if os.path.exists(fixture_path):
                with open(fixture_path, 'r', encoding='utf-8') as f:
                    self.champions[champ] = BeautifulSoup(f.read(), 'html.parser')

    def test_extract_icon_url_jayce(self):
        """Should extract icon URL for Jayce abilities."""
        soup = self.champions['Jayce']
        skill_div = soup.find('div', class_='skill_q')
        
        icon_url = extract_icon_url(skill_div, 'Jayce')
        
        self.assertIsNotNone(icon_url)
        self.assertTrue(icon_url.startswith('https://wiki.leagueoflegends.com/en-us/images/'))
        self.assertIn('Jayce', icon_url)

    def test_extract_icon_url_aatrox(self):
        """Should extract icon URL for Aatrox abilities."""
        soup = self.champions['Aatrox']
        skill_div = soup.find('div', class_='skill_q')
        
        icon_url = extract_icon_url(skill_div, 'Aatrox')
        
        self.assertIsNotNone(icon_url)
        self.assertTrue(icon_url.startswith('https://wiki.leagueoflegends.com/en-us/images/'))
        self.assertIn('Aatrox', icon_url)

    def test_extract_description_jayce(self):
        """Should extract description for Jayce abilities."""
        soup = self.champions['Jayce']
        skill_div = soup.find('div', class_='skill_q')
        
        description = extract_description(skill_div)
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 50)  # Description should be substantial

    def test_extract_description_aatrox(self):
        """Should extract description for Aatrox abilities."""
        soup = self.champions['Aatrox']
        skill_div = soup.find('div', class_='skill_q')
        
        description = extract_description(skill_div)
        
        self.assertIsNotNone(description)
        self.assertIsInstance(description, str)
        self.assertGreater(len(description), 50)  # Description should be substantial

    def test_icon_and_description_in_extracted_ability(self):
        """Icon and description should be included in extracted ability data."""
        soup = self.champions['Jayce']
        abilities = extract_all_abilities(soup, 'Jayce')
        
        # Find an ability with icon and description
        ability_with_data = next(
            (a for a in abilities if a.get('icon') and a.get('description')), 
            None
        )
        
        self.assertIsNotNone(ability_with_data)
        self.assertIn('icon', ability_with_data)
        self.assertIn('description', ability_with_data)
        self.assertTrue(ability_with_data['icon'].startswith('https://'))
        self.assertIsInstance(ability_with_data['description'], str)


if __name__ == '__main__':
    unittest.main(verbosity=2)
