import json
import sys
import threading
import types
from http.server import ThreadingHTTPServer

import pytest
import requests

from app.services import laya_client
from app.services.enrich import apply_pico_boost
from app.services.pipeline import rerank_relevance
from tools import eval_laya_groups, laya_worker


def test_worker_endpoint_matches_eval_state(tmp_path, monkeypatch):
    questions = {'group': {'type': 'choice', 'criteria': {'answers': 'yes', 'not': 'no'}}}
    (tmp_path / 'questions.json').write_text(json.dumps(questions))
    seen = []

    class Agent:
        def predict_batch(self, states, q, batch_size):
            seen.extend(states)
            assert q == questions and batch_size == 1
            return [{'answers': {'group': {'probabilities': {'answers': .75}}}}]

    monkeypatch.setitem(sys.modules, 'laya', types.SimpleNamespace(load=lambda path: Agent()))
    monkeypatch.setattr(laya_worker, '_relevance_agent', None)
    monkeypatch.setattr(laya_worker, '_relevance_checkpoint', None)
    monkeypatch.setattr(laya_worker, '_relevance_questions', None)
    laya_worker.configure_relevance(str(tmp_path))
    server = ThreadingHTTPServer(('127.0.0.1', 0), laya_worker.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        assert requests.get(url + '/health').json()['relevance_loaded'] is False
        paper = {'title': '  A   title ', 'abstract': 'First sentence. Second sentence! Third.'}
        result = requests.post(url + '/v1/relevance', json={'question': ' Q? ', 'papers': [paper]}).json()
        assert result['results'] == [{'p_answers': .75}]
        assert seen == [eval_laya_groups.group_state(' Q? ', paper['title'], eval_laya_groups.first_sentences(paper['abstract'], 2))]
        assert requests.get(url + '/health').json()['relevance_loaded'] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_checkpoint_without_answers_is_refused(tmp_path):
    (tmp_path / 'questions.json').write_text(json.dumps({'group': {'criteria': {'not': 'no'}}}))
    with pytest.raises(ValueError, match='answers'):
        laya_worker.configure_relevance(str(tmp_path))


@pytest.mark.parametrize('payload', [{}, {'results': []}, {'results': [{'p_answers': float('nan')}]},
                                     {'results': [{'p_answers': -0.1}]}, {'results': [{'p_answers': 1.1}]},
                                     {'results': [{'p_answers': True}]}])
def test_client_fails_closed(monkeypatch, payload):
    laya_client._reset_for_tests()
    monkeypatch.setenv('LITSIEVE_LAYA_URL', 'http://localhost:1234')
    response = types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    monkeypatch.setattr(laya_client.requests, 'post', lambda *args, **kwargs: response)
    assert laya_client.relevance('question', [{'title': 't', 'abstract': 'a'}]) is None
    assert laya_client.relevance('question', [{'title': 't', 'abstract': 'a'}]) is None
    laya_client._reset_for_tests()


def test_boost_survives_pico_sort():
    papers = [{'title': 'first', 'similarity_score': .6, 'abstract': '', 'pico': {}},
              {'title': 'second', 'similarity_score': .58, 'abstract': '', 'pico': {}}]
    rerank_relevance(papers, [0, 1])
    assert [p['title'] for p in papers] == ['second', 'first']
    assert papers[0]['similarity_score'] == pytest.approx(.625)
    apply_pico_boost(papers, 'question')
    assert [p['title'] for p in papers] == ['second', 'first']


@pytest.mark.parametrize('setting,sort,top_k,answer,expected_calls', [
    ('0', 'similarity', 10, [1.0] * 30, [10]),
    ('1', 'year', 10, [1.0] * 30, [10]),
    ('1', 'similarity', 10, None, [30, 10]),
    ('1', 'similarity', 10, [1.0] * 30, [30]),
    ('1', 'similarity', 40, [1.0] * 40, [40]),
])
def test_search_route_pool_and_fallback(monkeypatch, setting, sort, top_k, answer, expected_calls):
    import asyncio

    from app.routes import search
    from app.schemas import SearchRequest

    monkeypatch.setenv('LITSIEVE_LAYA_RERANK', setting)
    monkeypatch.setenv('LITSIEVE_LAYA_URL', 'http://localhost:1234')
    calls = []
    class Pipeline:
        db = object()
        embedding_model_name = 'test'
        def search_similar(self, query, top_k, **kwargs):
            calls.append(top_k)
            return [{'title': str(i), 'abstract': '', 'similarity_score': 1 - i * .001} for i in range(top_k)]
    pipeline = Pipeline()
    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr(search, 'current_user', lambda request: {'user_id': 1})
    monkeypatch.setattr(search, 'csrf_failed', lambda request: False)
    monkeypatch.setattr(search, 'get_pipeline', lambda uid: pipeline)
    monkeypatch.setattr(search, 'release_pipeline', lambda uid: None)
    monkeypatch.setattr(search, 'run_in_thread', run)
    monkeypatch.setattr(search, 'enrich_search_results', lambda *args, **kwargs: None)
    monkeypatch.setattr(search, 'log_question', lambda *args, **kwargs: None)
    monkeypatch.setattr(laya_client, 'relevance', lambda question, papers: answer)
    response = asyncio.run(search.api_search(SearchRequest(query_text='query', top_k=top_k, sort_by=sort), None))
    assert calls == expected_calls
    assert len(response['results']) == top_k
    if answer is None or setting == '0':
        assert response['results'][0]['similarity_score'] == 1
    elif sort == 'similarity':
        assert response['results'][0]['similarity_score'] == pytest.approx(1.045)


def test_client_unset_url_and_timeout(monkeypatch):
    laya_client._reset_for_tests()
    monkeypatch.delenv('LITSIEVE_LAYA_URL', raising=False)
    papers = [{'title': 't', 'abstract': 'a'}]
    assert laya_client.relevance('q', papers) is None
    monkeypatch.setenv('LITSIEVE_LAYA_URL', 'http://localhost:1234')
    wakes = []
    monkeypatch.setattr(laya_client, 'wake', lambda: wakes.append(True))
    def timeout(*args, **kwargs):
        raise requests.Timeout('late')
    monkeypatch.setattr(laya_client.requests, 'post', timeout)
    assert laya_client.relevance('q', papers) is None
    assert wakes == [True]
    laya_client._reset_for_tests()


def test_seed_search_does_not_call_relevance(monkeypatch):
    import asyncio

    from app.routes import search
    from app.schemas import SeedSearchRequest

    monkeypatch.setenv('LITSIEVE_LAYA_RERANK', 'true')
    monkeypatch.setenv('LITSIEVE_LAYA_URL', 'http://localhost:1234')
    class Pipeline:
        db = object()
        embedding_model_name = 'test'
        def search_by_seed(self, *args):
            return {'seed': 'seed', 'results': [{'title': 'paper', 'similarity_score': .5}]}
    async def run(func, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr(search, 'current_user', lambda request: {'user_id': 1})
    monkeypatch.setattr(search, 'csrf_failed', lambda request: False)
    monkeypatch.setattr(search, 'get_pipeline', lambda uid: Pipeline())
    monkeypatch.setattr(search, 'release_pipeline', lambda uid: None)
    monkeypatch.setattr(search, 'run_in_thread', run)
    monkeypatch.setattr(search, 'enrich_search_results', lambda *args, **kwargs: None)
    monkeypatch.setattr(search, 'log_question', lambda *args, **kwargs: None)
    def unexpected(*args):
        pytest.fail('seed search called relevance')
    monkeypatch.setattr(laya_client, 'relevance', unexpected)
    result = asyncio.run(search.api_search_seed(SeedSearchRequest(seed='seed'), None))
    assert result['results'][0]['similarity_score'] == .5
