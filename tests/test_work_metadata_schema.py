"""P1.1 migrations and output parity against main at 167a6ba."""

import json
import os
import random
import sqlite3
import string
import zlib
from contextlib import contextmanager

import numpy as np
import pytest

from app.services.citations import collection_to_apa, collection_to_bibtex, collection_to_ris
from app.services.pipeline import LiteratureSearchPipeline
from app.storage import dbconn, shares
from app.storage.database import (
    ARTICLE_COLUMNS,
    SEARCH_ARTICLE_COLUMNS,
    ArticleDatabase,
    omit_null_metadata,
)


@contextmanager
def _open(path):
    db = ArticleDatabase(str(path))
    try:
        yield db
    finally:
        db.close()


def _create_old_db(path):
    conn = dbconn.connect(str(path))
    try:
        conn.executescript(OLD_DDL)
        for article in ARTICLES:
            conn.execute(
                "INSERT INTO articles "
                "(article_id, source, title, abstract, year, authors, journal, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, '2020-01-02 03:04:05')",
                (article['article_id'], article['source'], article['title'], article['abstract'],
                 article['year'], json.dumps(article['authors']), article['journal']),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def old_path(tmp_path, monkeypatch):
    monkeypatch.delenv(dbconn.ENV_KEY, raising=False)
    path = tmp_path / 'old.db'
    _create_old_db(path)
    return path


def _legacy_rows(rows):
    return [{key: value for key, value in row.items() if key not in METADATA} for row in rows]


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def _schema(conn):
    return conn.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()


def _extra(conn, *, staging=False):
    table = 'staging_article_extra' if staging else 'article_extra'
    return conn.execute(f'SELECT * FROM {table} ORDER BY article_id, source').fetchall()


def test_old_ddl_migrates_idempotently_across_two_opens(old_path):
    with _open(old_path) as db:
        schema = _schema(db.conn)
        columns = {row[1]: row for row in db.conn.execute('PRAGMA table_info(articles)')}
        for name in METADATA:
            assert columns[name][2:5] == ('TEXT', 0, None)
        rows = db.get_all_articles()
        assert _bytes(_legacy_rows(rows)) == _bytes(MAIN_OUTPUTS['list'])
        assert all(row[name] is None for row in rows for name in METADATA)
        assert db.conn.execute('PRAGMA foreign_key_check').fetchall() == []
    with _open(old_path) as db:
        assert _schema(db.conn) == schema
        assert db.get_all_articles() == rows
        assert db.conn.execute('SELECT created_at FROM articles').fetchall() == [
            ('2020-01-02 03:04:05',), ('2020-01-02 03:04:05',),
        ]


def test_old_staging_migration_is_idempotent(old_path):
    with _open(old_path) as db:
        old_staging = OLD_DDL[OLD_DDL.index('CREATE TABLE staging_articles'):]
        db.conn.executescript(old_staging)
        db.migrate_schema()
        first_schema = _schema(db.conn)
        db.migrate_schema()
        assert _schema(db.conn) == first_schema
        columns = {row[1]: row for row in db.conn.execute('PRAGMA table_info(staging_articles)')}
        for name in METADATA:
            assert columns[name][2:5] == ('TEXT', 0, None)
        assert _extra(db.conn, staging=True) == []


@pytest.mark.parametrize('exporter, expected', [
    (collection_to_ris, 'ris'), (collection_to_bibtex, 'bibtex'), (collection_to_apa, 'apa'),
])
def test_legacy_exports_are_byte_identical_to_main(old_path, exporter, expected):
    with _open(old_path) as db:
        rows = db.get_library_export_rows()
        assert _bytes(_legacy_rows(rows)) == _bytes(MAIN_OUTPUTS['export_rows'])
        assert exporter(rows).encode('utf-8') == MAIN_OUTPUTS[expected].encode('utf-8')


def test_legacy_search_results_are_byte_identical_to_main(old_path):
    pipe = LiteratureSearchPipeline(db_path=str(old_path))
    try:
        pipe.db.insert_embeddings({
            (article['article_id'], article['source']): np.array([1.0, float(i)], dtype=np.float32)
            for i, article in enumerate(ARTICLES)
        }, model_name='general')
        rows = pipe.search_similar(
            'warming', top_k=10, query_embedding=np.array([1.0, 0.0], dtype=np.float32),
        )
        assert _bytes(rows) == _bytes(MAIN_OUTPUTS['search'])
        assert all(name not in row for row in rows for name in METADATA)
    finally:
        pipe.db.close()


def test_legacy_cluster_and_excluded_responses_match_main(old_path):
    key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
    with _open(old_path) as db:
        db.insert_clusters({key: (7, 'Oceans')})
        db.exclude_articles([key], reason='off_topic')
        cluster = [omit_null_metadata(dict(row)) for row in db.get_articles_by_cluster(7)]
        excluded = [omit_null_metadata(dict(row)) for row in db.get_excluded_items()]
        assert _bytes(cluster) == _bytes(MAIN_OUTPUTS['cluster'])
        assert _bytes(excluded) == _bytes(MAIN_OUTPUTS['excluded'])
        assert all(name not in row for row in cluster + excluded for name in METADATA)
        db.insert_articles([{**ARTICLES[0], **METADATA}], dedupe=False)
        filled = omit_null_metadata(dict(db.get_articles_by_cluster(7)[0]))
        assert {name: filled[name] for name in METADATA} == METADATA


def test_search_path_does_not_read_biblio(old_path, monkeypatch):
    seen = []
    original = ArticleDatabase.get_all_articles_with_clusters

    def wrapped(self, columns=ARTICLE_COLUMNS):
        seen.append(tuple(columns))
        return original(self, columns=columns)

    monkeypatch.setattr(ArticleDatabase, 'get_all_articles_with_clusters', wrapped)
    pipe = LiteratureSearchPipeline(db_path=str(old_path))
    try:
        pipe.db.insert_embeddings({
            (article['article_id'], article['source']): np.array([1.0, float(i)], dtype=np.float32)
            for i, article in enumerate(ARTICLES)
        }, model_name='general')
        pipe.search_similar(
            'warming', top_k=10, query_embedding=np.array([1.0, 0.0], dtype=np.float32),
        )
    finally:
        pipe.db.close()
    assert seen
    assert all('biblio' not in columns for columns in seen)
    assert SEARCH_ARTICLE_COLUMNS == ARTICLE_COLUMNS[:7]
    assert 'biblio' not in SEARCH_ARTICLE_COLUMNS


def test_excluded_summary_does_not_decode_unused_authors(old_path):
    key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
    with _open(old_path) as db:
        db.conn.execute('UPDATE articles SET authors = ?', ('legacy non-JSON value',))
        db.conn.commit()
        db.exclude_articles([key], reason='off_topic')
        row = db.get_excluded_items()[0]
        expected = {name: value for name, value in ARTICLES[0].items()
                    if name not in {'abstract', 'authors'}}
        expected['reason'] = 'off_topic'
        assert _legacy_rows([row]) == [expected]
        assert all(row[name] is None for name in METADATA)


@pytest.mark.parametrize('reader', [
    'all', 'by_id', 'seed_exact', 'seed_partial', 'seed_title', 'cluster', 'clusters', 'export',
    'excluded',
])
def test_every_article_reader_returns_metadata_and_joined_values(old_path, reader):
    article = {**ARTICLES[0], **METADATA}
    key = (article['article_id'], article['source'])
    with _open(old_path) as db:
        assert db.insert_articles([article], dedupe=False)['updated'] == 1
        db.insert_clusters({key: (7, 'Oceans')})
        db.exclude_articles([key], reason='off_topic')
        db.upsert_note(*key, note='Read chapter', starred=True)
        readers = {
            'all': lambda: db.get_all_articles()[0],
            'by_id': lambda: db.get_article_by_id(*key),
            'seed_exact': lambda: db.find_article_by_seed('10.1234/AB.CD'),
            'seed_partial': lambda: db.find_article_by_seed('ab.cd'),
            'seed_title': lambda: db.find_article_by_seed('Ocean'),
            'cluster': lambda: db.get_articles_by_cluster(7)[0],
            'clusters': lambda: db.get_all_articles_with_clusters()[key],
            'export': lambda: db.get_library_export_rows('starred')[0],
            'excluded': lambda: db.get_excluded_items('off_topic')[0],
        }
        row = readers[reader]()
        assert {name: row[name] for name in METADATA} == METADATA
        if reader == 'excluded':
            expected = {name: value for name, value in ARTICLES[0].items()
                        if name not in {'abstract', 'authors'}}
            assert {name: row[name] for name in expected} == expected
            assert 'abstract' not in row and 'authors' not in row
        else:
            assert {name: row[name] for name in ARTICLES[0]} == ARTICLES[0]
        if reader in {'cluster', 'clusters', 'export'}:
            assert row['cluster_label'] == 'Oceans'
        if reader in {'cluster', 'export'}:
            assert row['excluded'] is True
        if reader == 'export':
            assert row['note'] == 'Read chapter'
            assert row['starred'] is True
            assert row['exclusion_reason'] == 'off_topic'
            assert db.get_library_export_rows('included')[0]['article_id'] == ARTICLES[1]['article_id']
        if reader == 'excluded':
            assert row['reason'] == 'off_topic'
        assert db.find_article_by_seed(' ') is None
        assert db.get_article_by_id('missing', 'pubmed') is None


@pytest.mark.parametrize('staging', [False, True])
def test_upsert_preserves_metadata_on_null_but_keeps_legacy_updates(old_path, staging):
    article = {**ARTICLES[0], **METADATA}
    with _open(old_path) as db:
        if staging:
            db.ensure_staging_articles()
        assert db.insert_articles([article], dedupe=False, staging=staging)['dropped'] == 0
        for updates in ({}, dict.fromkeys(METADATA)):
            refreshed = {**ARTICLES[0], 'title': 'Updated title', 'year': None, **updates}
            assert db.insert_articles([refreshed], dedupe=False, staging=staging)['updated'] == 1
        if staging:
            db.replace_from_staging()
        row = db.get_article_by_id(article['article_id'], article['source'])
        assert row['title'] == 'Updated title'
        assert row['year'] is None
        assert {name: row[name] for name in METADATA} == METADATA
        db.insert_articles([{**article, 'work_type': 'book'}], dedupe=False)
        assert db.get_article_by_id(article['article_id'], article['source'])['work_type'] == 'book'


def test_doi_index_is_nonunique(old_path):
    with _open(old_path) as db:
        result = db.insert_articles([
            {**ARTICLES[0], **METADATA}, {**ARTICLES[1], **METADATA},
        ], dedupe=False)
        assert result['updated'] == 2
        assert db.conn.execute('SELECT COUNT(*) FROM articles WHERE doi = ?',
                               (METADATA['doi'],)).fetchone()[0] == 2
        indexes = db.conn.execute('PRAGMA index_list(articles)').fetchall()
        doi_indexes = [row for row in indexes if db.conn.execute(
            f'PRAGMA index_info({row[1]})'
        ).fetchall()[0][2] == 'doi']
        assert doi_indexes and all(row[2] == 0 for row in doi_indexes)


@pytest.mark.parametrize('staging', [False, True])
def test_provider_record_compresses_utf8_and_preserves_other_extra_fields(old_path, staging):
    article = ARTICLES[0]
    key = (article['article_id'], article['source'])
    record = {'title': 'Écologie 海洋', 'abstract': '海' * 10000}
    with _open(old_path) as db:
        if staging:
            db.ensure_staging_articles()
        table = 'staging_article_extra' if staging else 'article_extra'
        db.conn.execute(f'INSERT INTO {table} (article_id, source, provenance, fetch_run_id) '
                        'VALUES (?, ?, ?, ?)', (*key, '{"doi":"crossref"}', 7))
        db.conn.commit()
        db.store_provider_record(*key, record, staging=staging)
        row = _extra(db.conn, staging=staging)[0]
        assert row[2:5] == ('{"doi":"crossref"}', '[]', '[]')
        assert row[6:] == (None, 7)
        encoded = _bytes(record)
        assert len(encoded) > 4096 and len(row[5]) <= 4096
        assert zlib.decompress(row[5]) == encoded
        assert json.loads(zlib.decompress(row[5]).decode('utf-8')) == record


def test_provider_record_over_cap_is_null_and_never_truncated(old_path):
    key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
    rng = random.Random(77)
    record = {'payload': ''.join(rng.choices(string.ascii_letters + string.digits, k=12000))}
    assert len(zlib.compress(_bytes(record))) > 4096
    with _open(old_path) as db:
        db.store_provider_record(*key, {'small': 'first'})
        db.store_provider_record(*key, record)
        assert _extra(db.conn)[0][5:7] == (None, 'too_large')
        db.store_provider_record(*key, {'small': 'again'})
        assert _extra(db.conn)[0][6] is None
        assert json.loads(zlib.decompress(_extra(db.conn)[0][5])) == {'small': 'again'}


@pytest.mark.parametrize('size', [4096, 4097])
def test_provider_record_limit_is_inclusive(old_path, monkeypatch, size):
    key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
    compressed = b'x' * size
    monkeypatch.setattr('app.storage.database.zlib.compress', lambda encoded: compressed)
    with _open(old_path) as db:
        db.store_provider_record(*key, {'title': 'Boundary'})
        assert _extra(db.conn)[0][5:7] == (
            (compressed, None) if size == 4096 else (None, 'too_large')
        )


def test_extra_uses_composite_fk_and_cascades(old_path):
    with _open(old_path) as db:
        key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
        db.store_provider_record(*key, {'title': 'record'})
        with pytest.raises(sqlite3.IntegrityError):
            db.store_provider_record(key[0], 'wrong-source', {})
        db.conn.execute('DELETE FROM articles WHERE article_id = ? AND source = ?', key)
        db.conn.commit()
        assert _extra(db.conn) == []
        db.ensure_staging_articles()
        assert db.conn.execute('PRAGMA foreign_key_list(staging_article_extra)').fetchall() == []
        db.store_provider_record('not-live', 'crossref', {}, staging=True)
        assert len(_extra(db.conn, staging=True)) == 1


def test_replace_fetch_copies_metadata_and_all_extra_values(old_path):
    article = {**ARTICLES[0], **METADATA}
    key = (article['article_id'], article['source'])
    with _open(old_path) as db:
        db.store_provider_record(ARTICLES[1]['article_id'], ARTICLES[1]['source'], {'old': True})
        db.ensure_staging_articles()
        db.insert_articles([article], dedupe=False, staging=True)
        db.store_provider_record(*key, {'title': 'new record'}, staging=True)
        db.conn.execute('UPDATE staging_article_extra SET provenance=?, locations=?, related=?, '
                        'fetch_run_id=?', ('{"doi":"crossref"}', '[{"url":"https://example.org"}]',
                                         '[{"id":"parent"}]', 12))
        db.conn.execute("UPDATE staging_articles SET created_at='2020-01-02 03:04:05'")
        db.conn.commit()
        extra = _extra(db.conn, staging=True)
        assert db.replace_from_staging() == 1
        assert db.get_all_articles() == [article]
        assert _extra(db.conn) == extra
        assert db.conn.execute('SELECT created_at FROM articles').fetchone()[0] == '2020-01-02 03:04:05'
        assert not any(name.startswith('staging_') for _, name, _ in _schema(db.conn))


def test_interrupted_add_column_migration_recovers(old_path):
    conn = dbconn.connect(str(old_path))
    try:
        for name in ARTICLE_COLUMNS[7:11]:
            conn.execute(f'ALTER TABLE articles ADD COLUMN {name} TEXT')
        conn.commit()
        before = conn.execute(
            'SELECT rowid, created_at, article_id, source, title, abstract, year, authors, journal '
            'FROM articles ORDER BY rowid'
        ).fetchall()
    finally:
        conn.close()
    with _open(old_path) as db:
        after = db.conn.execute(
            'SELECT rowid, created_at, article_id, source, title, abstract, year, authors, journal '
            'FROM articles ORDER BY rowid'
        ).fetchall()
        assert after == before
        columns = {row[1] for row in db.conn.execute('PRAGMA table_info(articles)')}
        assert set(ARTICLE_COLUMNS).issubset(columns)
        assert db.conn.execute('PRAGMA foreign_key_check').fetchall() == []
        assert _bytes(_legacy_rows(db.get_all_articles())) == _bytes(MAIN_OUTPUTS['list'])
        assert all(row[name] is None for row in db.get_all_articles() for name in METADATA)


def _cipher_env(monkeypatch, cipher):
    if cipher:
        if os.environ.get('CI'):
            __import__('sqlcipher3')
        else:
            pytest.importorskip('sqlcipher3', reason='sqlcipher3-binary not installed')
        monkeypatch.setenv(dbconn.ENV_KEY, 'p11-fixture-key')
    else:
        monkeypatch.delenv(dbconn.ENV_KEY, raising=False)


_SWAP_TABLES = (
    'articles', 'article_extra', 'notes', 'screening', 'embeddings', 'key_points',
    'staging_articles', 'staging_article_extra',
)


@pytest.mark.parametrize('cipher', [False, True])
def test_failed_swap_rolls_back_then_retries(tmp_path, monkeypatch, cipher):
    _cipher_env(monkeypatch, cipher)
    path = tmp_path / ('encrypted.db' if cipher else 'old.db')
    _create_old_db(path)
    key = (ARTICLES[0]['article_id'], ARTICLES[0]['source'])
    other = (ARTICLES[1]['article_id'], ARTICLES[1]['source'])
    with _open(path) as db:
        db.insert_articles([{**ARTICLES[0], **METADATA}], dedupe=False)
        db.store_provider_record(*key, {'old': True})
        db.store_provider_record(*other, {'extra': True})
        db.upsert_note(*key, note='Keep my note')
        db.exclude_articles([key], reason='off_topic')
        db.insert_embeddings({
            key: np.array([1.0, 0.0], dtype=np.float32),
            other: np.array([0.0, 1.0], dtype=np.float32),
        }, model_name='general')
        db.insert_key_points({key: ['Kept AI point']}, origin='ai')
        db.insert_key_points({other: ['Extractive point']}, origin='extractive')
        db.ensure_staging_articles()
        db.insert_articles([{**ARTICLES[0], 'title': 'Replacement'}], staging=True)
        db.store_provider_record(*key, {'new': True}, staging=True)
        db.conn.execute("""CREATE TRIGGER fail_extra_copy BEFORE INSERT ON article_extra
                           BEGIN SELECT RAISE(ABORT, 'injected swap failure'); END""")
        db.conn.commit()
        before = {table: db.conn.execute(f'SELECT * FROM {table}').fetchall()
                  for table in _SWAP_TABLES}
        with pytest.raises(dbconn.integrity_errors(), match='injected swap failure'):
            db.replace_from_staging()
        assert {table: db.conn.execute(f'SELECT * FROM {table}').fetchall()
                for table in _SWAP_TABLES} == before
        assert not any(name.startswith('_swap_keep_') for _, name, _ in _schema(db.conn))
        db.conn.execute('DROP TRIGGER fail_extra_copy')
        db.conn.commit()
        assert db.replace_from_staging() == 1
        assert db.get_article_by_id(*key)['title'] == 'Replacement'
        assert db.get_article_by_id(*other) is None
        assert json.loads(zlib.decompress(_extra(db.conn)[0][5])) == {'new': True}
        assert db.get_notes_map()[key]['note'] == 'Keep my note'
        assert db.get_excluded_keys() == {key}
        assert db.get_key_points_map()[key] == ['Kept AI point']
        assert other not in db.get_key_points_map()
        assert db.get_embedding_keys() == set()
        assert not any(name.startswith('staging_') for _, name, _ in _schema(db.conn))
        assert not any(name.startswith('_swap_keep_') for _, name, _ in _schema(db.conn))


@pytest.mark.parametrize('cleanup', ['startup', 'drop', 'reset', 'empty_swap', 'start_over'])
def test_both_staging_tables_are_cleaned(old_path, cleanup):
    with _open(old_path) as db:
        db.ensure_staging_articles()
        db.store_provider_record('orphan', 'crossref', {}, staging=True)
        if cleanup == 'startup':
            with _open(old_path) as reopened:
                assert not any(name.startswith('staging_') for _, name, _ in _schema(reopened.conn))
            return
        if cleanup == 'reset':
            db.reset_staging_articles()
            assert _extra(db.conn, staging=True) == []
            assert db.count_staging_articles() == 0
            return
        if cleanup == 'drop':
            db.drop_staging_articles()
        elif cleanup == 'empty_swap':
            assert db.replace_from_staging() == 0
        else:
            db.keep_starred_and_noted()
        assert not any(name.startswith('staging_') for _, name, _ in _schema(db.conn))


def test_sqlcipher_old_schema_migrates_across_two_opens(tmp_path, monkeypatch):
    if os.environ.get('CI'):
        __import__('sqlcipher3')
    else:
        pytest.importorskip('sqlcipher3', reason='sqlcipher3-binary not installed')
    monkeypatch.setenv(dbconn.ENV_KEY, 'p11-fixture-key')
    path = tmp_path / 'encrypted.db'
    _create_old_db(path)
    with _open(path) as db:
        assert _bytes(_legacy_rows(db.get_all_articles())) == _bytes(MAIN_OUTPUTS['list'])
        assert db.insert_articles([{**ARTICLES[0], **METADATA}], dedupe=False)['updated'] == 1
        db.store_provider_record(ARTICLES[0]['article_id'], ARTICLES[0]['source'], {'encrypted': True})
        schema = _schema(db.conn)
    with _open(path) as db:
        assert _schema(db.conn) == schema
        assert db.get_all_articles()[0]['doi'] == METADATA['doi']
        assert len(_extra(db.conn)) == 1
    assert path.read_bytes()[:16] != b'SQLite format 3\x00'


def test_clone_migrated_library_keeps_hot_fields_and_drops_extras(old_path, tmp_path, monkeypatch):
    destination = tmp_path / 'clone.db'
    monkeypatch.setattr(shares, 'library_db_path',
                        lambda user, library: old_path if user == 'owner' else destination)
    with _open(old_path) as db:
        db.insert_articles([{**ARTICLES[0], **METADATA}], dedupe=False)
        db.store_provider_record(ARTICLES[0]['article_id'], ARTICLES[0]['source'], {'private': True})
        db.ensure_staging_articles()
        db.store_provider_record('private-stage', 'crossref', {}, staging=True)
        original = db.get_all_articles()
        extra = _extra(db.conn)
    assert 'article_extra' not in shares.CLONE_TABLES
    assert shares.clone_library_data('owner', 'library', 'recipient', 'copy')['articles'] == 2
    with _open(destination) as db:
        assert db.get_all_articles() == original
        assert _extra(db.conn) == []
        assert not any(name.startswith('staging_') for _, name, _ in _schema(db.conn))
    with _open(old_path) as db:
        assert _extra(db.conn) == extra


# Copied from the CREATE statements on main at 167a6ba, before P1.1.
OLD_DDL = """
CREATE TABLE articles (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                title TEXT NOT NULL,
                abstract TEXT NOT NULL,
                year TEXT,
                authors TEXT,
                journal TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source)
            );

CREATE TABLE embeddings (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                embedding BLOB NOT NULL,
                dtype TEXT,
                shape TEXT,
                model_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE clusters (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                cluster_id INTEGER,
                cluster_label TEXT,
                representative_title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE screening (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                reason TEXT NOT NULL DEFAULT 'manual',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE notes (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                note TEXT NOT NULL DEFAULT '',
                starred INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE key_points (
                article_id TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'pubmed',
                bullets TEXT NOT NULL DEFAULT '[]',
                origin TEXT NOT NULL DEFAULT 'extractive',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source),
                FOREIGN KEY (article_id, source) REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE reader_explanations (
                article_id        TEXT NOT NULL,
                source            TEXT NOT NULL DEFAULT 'pubmed',
                audience          TEXT NOT NULL,
                abstract_hash     TEXT NOT NULL,
                prompt_version    TEXT NOT NULL,
                verifier_version  TEXT NOT NULL DEFAULT 'v1',
                content_json      TEXT NOT NULL,
                verification_json TEXT NOT NULL,
                provider          TEXT,
                model             TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (article_id, source, audience),
                FOREIGN KEY (article_id, source)
                    REFERENCES articles (article_id, source)
                    ON DELETE CASCADE
            );

CREATE TABLE staging_articles (
                    article_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'pubmed',
                    title TEXT NOT NULL,
                    abstract TEXT NOT NULL,
                    year TEXT,
                    authors TEXT,
                    journal TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (article_id, source)
                );
"""

ARTICLES = [{'article_id': '10.1234/ab.cd',
  'source': 'crossref',
  'title': 'Ocean {Warming} Trends',
  'abstract': 'Seas are\nwarming rapidly.',
  'year': '2021',
  'authors': ['Ada Lovelace', 'Grace Hopper'],
  'journal': 'Nature Climate'},
 {'article_id': '12345',
  'source': 'pubmed',
  'title': 'A clinical trial',
  'abstract': 'Methods and results.',
  'year': 'Unknown',
  'authors': ['Doe J'],
  'journal': 'Lancet'}]

# Captured with main at 167a6ba, before changing database.py.
MAIN_OUTPUTS = {'ris': 'TY  - JOUR\n'
        'TI  - A clinical trial\n'
        'AU  - Doe J\n'
        'JO  - Lancet\n'
        'AB  - Methods and results.\n'
        'UR  - https://pubmed.ncbi.nlm.nih.gov/12345/\n'
        'ID  - pubmed:12345\n'
        'ER  - \n'
        '\n'
        'TY  - JOUR\n'
        'TI  - Ocean {Warming} Trends\n'
        'AU  - Ada Lovelace\n'
        'AU  - Grace Hopper\n'
        'PY  - 2021\n'
        'JO  - Nature Climate\n'
        'AB  - Seas are warming rapidly.\n'
        'DO  - 10.1234/ab.cd\n'
        'UR  - https://doi.org/10.1234/ab.cd\n'
        'ID  - crossref:10.1234/ab.cd\n'
        'ER  - \n',
 'bibtex': '@article{pubmed_12345,\n'
           '  title = {{A clinical trial}},\n'
           '  author = {Doe J},\n'
           '  journal = {Lancet},\n'
           '  url = {https://pubmed.ncbi.nlm.nih.gov/12345/},\n'
           '  note = {Source: pubmed}\n'
           '}\n'
           '\n'
           '@article{crossref_10_1234_ab_cd,\n'
           '  title = {{Ocean \\{Warming\\} Trends}},\n'
           '  author = {Ada Lovelace and Grace Hopper},\n'
           '  year = {2021},\n'
           '  journal = {Nature Climate},\n'
           '  doi = {10.1234/ab.cd},\n'
           '  url = {https://doi.org/10.1234/ab.cd},\n'
           '  note = {Source: crossref}\n'
           '}\n',
 'apa': 'Doe, J. (n.d.). A clinical trial. *Lancet*. https://pubmed.ncbi.nlm.nih.gov/12345/\n'
        '\n'
        'Lovelace, A., & Hopper, G. (2021). Ocean {Warming} Trends. *Nature Climate*. '
        'https://doi.org/10.1234/ab.cd\n',
 'list': [{'article_id': '10.1234/ab.cd',
           'source': 'crossref',
           'title': 'Ocean {Warming} Trends',
           'abstract': 'Seas are\nwarming rapidly.',
           'year': '2021',
           'authors': ['Ada Lovelace', 'Grace Hopper'],
           'journal': 'Nature Climate'},
          {'article_id': '12345',
           'source': 'pubmed',
           'title': 'A clinical trial',
           'abstract': 'Methods and results.',
           'year': 'Unknown',
           'authors': ['Doe J'],
           'journal': 'Lancet'}],
 'export_rows': [{'article_id': '12345',
                  'source': 'pubmed',
                  'title': 'A clinical trial',
                  'abstract': 'Methods and results.',
                  'year': 'Unknown',
                  'authors': ['Doe J'],
                  'journal': 'Lancet',
                  'cluster_id': None,
                  'cluster_label': None,
                  'excluded': False,
                  'exclusion_reason': '',
                  'note': '',
                  'starred': False},
                 {'article_id': '10.1234/ab.cd',
                  'source': 'crossref',
                  'title': 'Ocean {Warming} Trends',
                  'abstract': 'Seas are\nwarming rapidly.',
                  'year': '2021',
                  'authors': ['Ada Lovelace', 'Grace Hopper'],
                  'journal': 'Nature Climate',
                  'cluster_id': None,
                  'cluster_label': None,
                  'excluded': False,
                  'exclusion_reason': '',
                  'note': '',
                  'starred': False}],
 'search': [{'article_id': '10.1234/ab.cd',
             'source': 'crossref',
             'title': 'Ocean {Warming} Trends',
             'abstract': 'Seas are\nwarming rapidly.',
             'year': '2021',
             'authors': ['Ada Lovelace', 'Grace Hopper'],
             'journal': 'Nature Climate',
             'cluster_id': None,
             'cluster_label': None,
             'similarity_score': 0.9085,
             'semantic_score': 1.0,
             'lexical_score': 0.5424,
             'word_bonus': 0.1085},
            {'article_id': '12345',
             'source': 'pubmed',
             'title': 'A clinical trial',
             'abstract': 'Methods and results.',
             'year': 'Unknown',
             'authors': ['Doe J'],
             'journal': 'Lancet',
             'cluster_id': None,
             'cluster_label': None,
             'similarity_score': 0.5657,
             'semantic_score': 0.7071,
             'lexical_score': 0.0,
             'word_bonus': 0.0}],
 'cluster': [{'article_id': '10.1234/ab.cd',
              'source': 'crossref',
              'title': 'Ocean {Warming} Trends',
              'abstract': 'Seas are\nwarming rapidly.',
              'year': '2021',
              'authors': ['Ada Lovelace', 'Grace Hopper'],
              'journal': 'Nature Climate',
              'cluster_label': 'Oceans',
              'excluded': True}],
 'excluded': [{'article_id': '10.1234/ab.cd',
               'source': 'crossref',
               'title': 'Ocean {Warming} Trends',
               'year': '2021',
               'journal': 'Nature Climate',
               'reason': 'off_topic'}]}

METADATA = {'work_type': 'book-chapter',
 'provider_type': 'chapter',
 'doi': '10.1234/chapter',
 'container_title': 'Collected Studies',
 'host_name': 'Example Repository',
 'oa_status': 'green',
 'best_oa_url': 'https://example.org/chapter.pdf',
 'evidence_basis': 'metadata',
 'biblio': '{"publisher": "Example Press", "volume": "2", "issue": "3", "pages": "7-19", "isbn": '
           '["9781234567890"], "editors": ["Editor E"], "published_date": "2020-01-02", "license": '
           '"cc-by", "parent_book_id": "book:1"}'}
