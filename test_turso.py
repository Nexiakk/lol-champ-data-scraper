import os
from dotenv import load_dotenv

# Load from .env if present
load_dotenv()

from scraper.turso_utils import init_turso, get_db

def test_store():
    print("Init Turso:", init_turso())
    db = get_db()
    
    mock_data = {
        "name": "TestChamp",
        "imageName": "test.png",
        "patch": "14.1",
        "roles": {"top": {}},
        "abilities": [{"id": "Q"}]
    }
    
    success = db.store_champion_data("testchamp", mock_data)
    print("Store success:", success)

if __name__ == "__main__":
    test_store()
