"""Offline, source-pinned task selection. Listing never asserts runtime readiness."""
from ._version import __version__
from ._libero_tasks import TASKS
from .schema import require, text

LIBERO_COMMIT = 'f78abd68ee283de9f9be3c8f7e2a9ad60246e95c'
SUITES = {
    'libero_spatial': 'Spatial relationships and object placement',
    'libero_object': 'Object variation with a shared pick-and-place objective',
    'libero_goal': 'Different manipulation goals in related scenes',
    'libero_10': 'Ten longer downstream manipulation tasks',
    'libero_90': 'Ninety tasks intended for upstream training in the original protocol',
}


def _tasks():
    for suite in SUITES:
        for index, name in enumerate(TASKS[suite]):
            yield {'id': f'{suite}.{index}', 'suite': suite, 'task_index': index,
                   'name': name, 'display_name': name.replace('_', ' '),
                   'availability': 'listed', 'robot': 'Panda',
                   'policy_compatibility': 'not_established', 'training_exposure': 'not_assessed'}


def list_tasks(*, suite=None, query=None):
    """Return fresh catalogue records; no simulator import, assets, model or I/O."""
    require(suite is None or isinstance(suite, str) and suite in SUITES, 'unknown catalogue suite')
    if query is not None:
        text(query, 'catalogue query', 200)
    tasks = [task for task in _tasks() if (suite is None or task['suite'] == suite)
             and (query is None or query.casefold() in task['display_name'].casefold()
                  or query.casefold() in task['name'].casefold())]
    return {'catalogue_schema_version': 1, 'status': 'tasks_listed',
            'producer': {'name': 'policydiff', 'version': __version__},
            'source': {'name': 'LIBERO', 'commit': LIBERO_COMMIT, 'task_order_index': 0,
                       'url': f'https://github.com/Lifelong-Robot-Learning/LIBERO/tree/{LIBERO_COMMIT}'},
            'catalogue_task_count': sum(map(len, TASKS.values())), 'selected_task_count': len(tasks),
            'suites': [{'id': name, 'description': description, 'task_count': len(TASKS[name])}
                       for name, description in SUITES.items()],
            'selection': {'suite': suite, 'query': query}, 'tasks': tasks,
            'limitations': ['Listed tasks are not runtime checks, successful trials or policy compatibility claims.',
                            'Task IDs use the pinned source order; do not apply an alternate upstream task permutation.',
                            'Original suite membership does not establish your policy training exposure or held-out generalization.',
                            'Task assets and a compatible simulator/policy adapter are required for execution.']}


def resolve_task(task_id):
    text(task_id, 'catalogue task id', 80)
    for task in _tasks():
        if task['id'] == task_id:
            return task
    require(False, 'unknown catalogue task id; use catalog to select an exact ID')
