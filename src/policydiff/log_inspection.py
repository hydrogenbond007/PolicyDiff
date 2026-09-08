"""Read-only accounting for explicitly selected external logs, never a policy comparison."""
from collections import Counter
import math

from . import __version__
from .schema import integer, require, text

MAX_LOG_SCENES = 1000
MAX_LOG_EPOCHS = 30000
MAX_LOG_SCORERS = 100
ANNOTATIONS = ('operator_judgements', 'judgement_sources', 'termination_reasons')
METADATA = ('policy_config', 'embodiment_info', 'scene_metadata', 'trial_metadata')
LIMITATIONS = (
    'Selected Inspect Robots v1 fields only, not validation of the complete upstream schema.',
    'Run/scene success is execution status, not task success; score names and numbers have no inferred outcome semantics.',
    'Empty epoch records contain no scores in this snapshot, not proof of an ungraded trial or error; the upstream live writer also leaves completed epochs empty.',
    'Recorded run status does not establish current process liveness; absent annotations are unknown, not negative judgements.',
    'Only recorded epochs are counted; planned or never-started trials cannot be reconstructed from this log.',
    'Metadata contents, frames, transcripts, errors and referenced assets are not inspected or followed.',
    'Identity presence describes recorded values, not their types, truth or sufficiency; empty containers do not identify why data is missing.',
    'Checkpoint lineage, matched physical state, policy randomness, protocol equality and study design are not established; metadata may contain additional evidence.',
    'No comparison, inference, import manifest, readiness score or deployment verdict is produced.',
)


def _object(value, location):
    require(isinstance(value, dict), f'{location} must be an object')
    return value


def _array(value, location, maximum):
    require(isinstance(value, list) and len(value) <= maximum,
            f'{location} must be an array of at most {maximum} entries')
    return value


def _scores(value, location):
    _object(value, location)
    require(len(value) <= MAX_LOG_SCORERS, f'{location} exceeds the 100 scorer limit')
    for name, score in value.items():
        text(name, f'{location} scorer name', 200)
        try:
            finite = type(score) in (int, float) and math.isfinite(score)
        except OverflowError:
            finite = False
        require(finite, f'{location} scores must be finite numbers, not Booleans or strings')


def _presence(container, key):
    if key not in container:
        return 'absent'
    value = container[key]
    if value is None:
        return 'null'
    if isinstance(value, (str, list, dict)) and not value:
        return 'empty'
    return 'recorded'


def _annotations(sample, name, count, location):
    state = _presence(sample, name)
    if state == 'absent':
        return {'state': state, 'entries': 0, 'non_null': 0, 'null': 0, 'unannotated_epochs': count}
    values = _array(sample[name], f'{location}/{name}', MAX_LOG_EPOCHS)
    # Older schema-v1 logs use [] even when epochs exist. Never pad the source.
    require(len(values) in (0, count), f'{location}/{name} must be empty or parallel to epochs')
    for value in values:
        if value is not None:
            text(value, f'{location}/{name} entry', 200)
    non_null = sum(value is not None for value in values)
    return {'state': state, 'entries': len(values), 'non_null': non_null,
            'null': len(values) - non_null, 'unannotated_epochs': count - non_null}


def inspect_log(log, *, source_format):
    """Inventory a selected external log. No guessing, pairing, rescoring or I/O."""
    require(source_format == 'inspect-robots', 'unsupported log format; select inspect-robots explicitly')
    _object(log, 'log')
    require(type(log.get('version')) is int and log['version'] == 1,
            'unsupported Inspect Robots log version; only version 1 is inspected')
    status = log.get('status')
    require(status in ('started', 'success', 'error', 'cancelled'), 'unsupported run status')
    spec = _object(log.get('eval'), '/eval')
    results = _object(log.get('results'), '/results')
    samples = _array(log.get('samples'), '/samples', MAX_LOG_SCENES)
    declared = {}
    for field, maximum in (('total_scenes', MAX_LOG_SCENES), ('total_trials', MAX_LOG_EPOCHS)):
        declared[field] = integer(results.get(field), f'/results/{field}', 0, maximum)
    declared['errored_trials'] = (integer(results['errored_trials'], '/results/errored_trials', 0,
                                          MAX_LOG_EPOCHS) if 'errored_trials' in results else None)
    if 'metrics' in results:
        _scores(results['metrics'], '/results/metrics')
    for name in METADATA[:2]:
        if name in spec:
            _object(spec[name], f'/eval/{name}')
    scenes, ids, score_counts, annotation_counts = [], set(), Counter(), Counter()
    epoch_count = empty_count = operator_without_judgement = 0
    for index, sample in enumerate(samples):
        location = f'/samples/{index}'
        _object(sample, location)
        scene_id = text(sample.get('scene_id'), f'{location}/scene_id', 512)
        require(scene_id not in ids, f'{location}/scene_id duplicates an earlier scene')
        ids.add(scene_id)
        require(sample.get('status') in ('started', 'success', 'error', 'cancelled'),
                f'{location}/status is unsupported')
        epochs = _array(sample.get('epochs'), f'{location}/epochs', MAX_LOG_EPOCHS)
        count = len(epochs)
        epoch_count += count
        require(epoch_count <= MAX_LOG_EPOCHS, 'log exceeds the 30000 recorded epoch limit')
        annotations = {name: _annotations(sample, name, count, location) for name in ANNOTATIONS}
        if 'scene_metadata' in sample:
            _object(sample['scene_metadata'], f'{location}/scene_metadata')
        if 'trial_metadata' in sample:
            metadata = _array(sample['trial_metadata'], f'{location}/trial_metadata', MAX_LOG_EPOCHS)
            require(len(metadata) in (0, count), f'{location}/trial_metadata must be empty or parallel to epochs')
            for entry in metadata:
                _object(entry, f'{location}/trial_metadata entry')
        if 'reduced' in sample:
            _scores(sample['reduced'], f'{location}/reduced')
        empty = sum(not epoch for epoch in epochs)
        empty_count += empty
        judgements = sample.get('operator_judgements', [])
        for epoch_index, epoch in enumerate(epochs):
            _scores(epoch, f'{location}/epochs/{epoch_index}')
            score_counts.update(epoch.keys())
            require(len(score_counts) <= MAX_LOG_SCORERS, 'log exceeds the 100 distinct scorer limit')
            if 'operator' in epoch and (not judgements or judgements[epoch_index] is None):
                operator_without_judgement += 1
        for name in ANNOTATIONS:
            annotation_counts[name] += annotations[name]['non_null']
        scenes.append({'index': index, 'scene_id': scene_id, 'execution_status': sample['status'],
                       'epoch_records': count, 'scored_epoch_records': count - empty,
                       'empty_epoch_records': empty, 'annotations': annotations,
                       'metadata_presence': {name: _presence(sample, name) for name in METADATA[2:]}})
    issues = []
    if declared['total_scenes'] != len(scenes):
        issues.append('declared_scene_count_differs_from_recorded_scenes')
    if declared['total_trials'] != epoch_count:
        issues.append('declared_trial_count_differs_from_recorded_epochs')
    errored = declared['errored_trials']
    if errored is not None and (errored > declared['total_trials'] or errored > empty_count):
        issues.append('declared_errors_exceed_declared_trials_or_empty_epochs')
    return {
        'log_inspection_schema_version': 1, 'status': 'log_inspected',
        'producer': {'name': 'policydiff', 'version': __version__}, 'inputs': None,
        'source_format': source_format, 'source_schema_version': 1, 'run_status': status,
        'comparison_support': 'not_established',
        'identity_presence': {name: _presence(spec, name) for name in (
            'task', 'policy', 'embodiment', 'inspect_robots_version', 'git_commit', 'seed',
            'max_steps', 'max_seconds', 'policy_config', 'embodiment_info')},
        'declared_counts': declared,
        'observed_counts': {'scenes': len(scenes), 'epoch_records': epoch_count,
                            'scored_epoch_records': epoch_count - empty_count,
                            'empty_epoch_records': empty_count,
                            'operator_scores_without_recorded_judgement': operator_without_judgement},
        'accounting': {'scope': 'in_progress' if status == 'started' else 'terminal', 'issues': issues,
                       'note': 'Live logs may include an active epoch before the completed-trial counter advances; mismatches are not automatically corruption.'},
        'annotation_coverage': {name: {'non_null_epochs': annotation_counts[name],
                                      'unannotated_epochs': epoch_count - annotation_counts[name]}
                                for name in ANNOTATIONS},
        'scorers': [{'name': name, 'scored_epoch_records': count, 'epochs_without_score': epoch_count - count}
                    for name, count in sorted(score_counts.items())],
        'scenes': scenes, 'limitations': list(LIMITATIONS),
    }
