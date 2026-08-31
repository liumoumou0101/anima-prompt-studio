import sqlite3

from anima_prompt_studio.repositories.tag_database import TagDatabase


def make_database(path):
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE tags(name TEXT PRIMARY KEY, output_name TEXT, category INTEGER, post_count INTEGER, is_deprecated INTEGER, created_at TEXT);
        CREATE TABLE aliases(antecedent TEXT PRIMARY KEY, consequent TEXT);
        CREATE VIRTUAL TABLE tag_search USING fts5(term, canonical UNINDEXED);
        INSERT INTO tags VALUES('pleated_skirt','pleated skirt',0,100000,0,'2020-01-01');
        INSERT INTO tags VALUES('school_uniform','school uniform',0,200000,0,'2020-01-01');
        INSERT INTO tags VALUES('skirt','skirt',0,300000,0,'2020-01-01');
        INSERT INTO tags VALUES('keqing_(genshin_impact)','keqing (genshin impact)',4,50000,0,'2020-01-01');
        INSERT INTO tags VALUES('genshin_impact','genshin impact',3,900000,0,'2020-01-01');
        INSERT INTO aliases VALUES('schoolwear','school_uniform');
        INSERT INTO tag_search VALUES('pleated skirt','pleated_skirt');
        INSERT INTO tag_search VALUES('school uniform','school_uniform');
        INSERT INTO tag_search VALUES('keqing genshin impact','keqing_(genshin_impact)');
        INSERT INTO tag_search VALUES('genshin impact','genshin_impact');
    """)
    connection.close()


def test_exact_ngram_and_alias_matching(tmp_path):
    path = tmp_path / "tags.db"; make_database(path)
    db = TagDatabase(path)
    assert {x["output_name"] for x in db.match_english("wearing a pleated skirt and schoolwear")} == {"pleated skirt", "school uniform"}


def test_fts_search(tmp_path):
    path = tmp_path / "tags.db"; make_database(path)
    result = TagDatabase(path).search("pleat")
    assert result[0]["output_name"] == "pleated skirt"


def test_search_can_filter_character_and_copyright_categories(tmp_path):
    path = tmp_path / "tags.db"; make_database(path)
    db = TagDatabase(path)
    characters = db.search("keqing", categories={4})
    assert characters == [{
        "canonical_name": "keqing_(genshin_impact)",
        "output_name": "keqing (genshin impact)",
        "category": 4,
        "post_count": 50000,
    }]
    assert db.search("keqing", categories={3}) == []
