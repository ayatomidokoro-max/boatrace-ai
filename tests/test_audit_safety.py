import json
from pathlib import Path
from datetime import UTC, datetime, timedelta

from boatrace_ai.models import Race, Entrant
from boatrace_ai.scoring import analyze_race
from boatrace_ai.storage import Repository
from boatrace_ai.timing import eligibility, upcoming
from boatrace_ai.results import parse_official, reconcile
from boatrace_ai.learning import _metrics


def test_utc_jst_boundary_and_unknown_time_fail_closed():
    assert eligibility('2026-10-19 00:38:59','2026-10-19 09:39:00') == 'eligible'
    assert eligibility('2026-10-19 00:39:00','2026-10-19 09:39:00') == 'after_deadline'
    assert eligibility('2026-10-19T09:39:00+09:00','2026-10-19T00:39:00Z') == 'after_deadline'
    assert eligibility(None,'invalid') == 'missing_time'
    assert not upcoming(None,datetime.now(UTC))


def test_display_and_evaluation_use_same_exported_version(tmp_path):
    repo=Repository(tmp_path/'versions.sqlite3')
    tomorrow=(datetime.now(UTC)+timedelta(days=1)).isoformat()
    race=Race('2030-01-01',1,'test',1,closed_at=tomorrow,
              entrants=[Entrant(lane=i) for i in range(1,7)])
    first=analyze_race(race,min_confidence=0,min_margin=0)
    run=repo.start_run(race.race_date,'now','test');repo.save(run,first)
    assert repo.performance_payload()['races'][0]['evaluation_status']=='unpublished_before_deadline'
    repo.publish_predictions([first],{})
    second=analyze_race(race,min_confidence=0,min_margin=0)
    second.trifectas=['6-5-4']
    run=repo.start_run(race.race_date,'now','test');repo.save(run,second)
    # New, unexported data does not replace the version the user saw.
    assert repo.performance_payload()['races'][0]['trifectas']==first.trifectas
    repo.publish_predictions([second],{'confidence_top3':[{'stadium_number':1,'race_number':1}]})
    item=repo.performance_payload()['races'][0]
    assert item['trifectas']==['6-5-4']
    assert item['recommendation_categories']==['confidence_top3']
    with repo.connect() as db:
        assert db.execute('select count(*) from prediction_versions').fetchone()[0]==2
        # Original first snapshot is preserved, never rewritten by latest publication.
        assert json.loads(db.execute('select trifectas_json from race_predictions').fetchone()[0])==first.trifectas


def test_missing_exhibition_and_weather_cannot_be_full_coverage():
    entrants=[Entrant(lane=i,national_win_rate=5,national_top2=30,local_win_rate=5,
        average_start_timing=.15,motor_top2=30,boat_top2=30,flying_count=0) for i in range(1,7)]
    analysis=analyze_race(Race('2030-01-01',1,'test',1,entrants=entrants))
    assert analysis.data_completeness==.583
    assert analysis.confidence > analysis.data_completeness


def test_learning_obeys_live_skip_and_rejects_future_results():
    race=Race('2030-01-01',1,'test',1,entrants=[Entrant(lane=i) for i in range(1,7)])
    analysis=analyze_race(race)
    row={'analysis_json':json.dumps(analysis.to_dict()),'result_places_json':'[1,2,3]',
         'result_trifecta':'1-2-3','trifecta_payout':1000}
    assert _metrics([row],__import__('boatrace_ai.scoring',fromlist=['WEIGHTS']).WEIGHTS)['stake']==0


def test_official_parser_and_unavailable_are_distinct():
    result=parse_official((Path(__file__).parent/'fixtures/official-result.html').read_text(encoding='utf8'))
    assert result=={'status':'official_confirmed','combination':'5-3-6','payout':7990,'places':[5,3,6]}
    assert parse_official('<html>Not yet published</html>')['status']=='not_published'
    assert parse_official('<p>このレースは中止</p>')['status']=='cancelled'


def test_reconciliation_preserves_prediction_and_records_provenance(tmp_path):
    repo=Repository(tmp_path/'results.sqlite3')
    race=Race('2026-01-01',1,'test',1,closed_at='2026-01-01 12:00:00')
    run=repo.start_run(race.race_date,'now','test');repo.save(run,analyze_race(race))
    report=reconcile(repo,fetch=lambda r:('https://www.boatrace.jp/fixture',{
        'status':'official_confirmed','combination':'5-3-6','payout':7990,'places':[5,3,6]}))
    assert report['checked']==1
    item=repo.performance_payload()['races'][0]
    assert item['result_trifecta']=='5-3-6'
    assert item['result_status']=='official_confirmed'
    assert item['evaluation_status']!='eligible'
    assert item['stake']==0
