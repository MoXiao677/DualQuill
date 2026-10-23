"""Read-only simulation of existing planning commands; never edits manuscript."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from novel_writer.application.full_book_planning import FullBookPlanning
from novel_writer.domain.full_book_planning import deviation_report
from novel_writer.domain.tasks import require


class PlanningSandbox:
    """Run the authoritative command validators against an isolated state copy."""

    def __init__(self, state):
        self.state = deepcopy(state)

    def get(self, project):
        require(project == self.state['document']['project']['id'], '规划项目不匹配')
        return deepcopy(self.state)

    def atomic(self, project, operation, **kwargs):
        self.get(project)
        updated, result = operation(deepcopy(self.state))
        if updated is not None:
            self.state = updated
        return result


def simulate(state, actions, identity, linked_plans=()):
    """Return simulated state and reason counts using the existing C07/F1 engines."""
    require(type(actions) is list and 1 <= len(actions) <= 20, '一次规划提案须含1至20项变更')
    sandbox = PlanningSandbox(state)
    service = SimpleNamespace(repository=sandbox, get=sandbox.get)
    project = state['document']['project']['id']
    engine = FullBookPlanning(service)
    for index, action in enumerate(actions):
        require(type(action) is dict and set(action) == {'action', 'values'}, '规划变更字段非法')
        require(type(action['values']) is dict, '规划变更参数须为对象')
        require(not {'operation_id', 'expected_revision'} & set(action['values']), '提案不可指定内部事务身份')
        values = dict(action['values'], operation_id=str(uuid5(NAMESPACE_URL, identity + '/change/' + str(index))),
                      expected_revision=state['revision'])
        if action['action'] == 'prepare_plan':
            from novel_writer.application.knowledge import command
            plan = next((p for p in sandbox.state.get('planning_proposals', []) if p['id'] in linked_plans), None)
            if plan is None:
                plan = command(service, project, 'prepare_plan', values)
            command(service, project, 'decide_plan', dict(operation_id=str(uuid5(NAMESPACE_URL, identity + '/accept/' + str(index))),
                    expected_revision=state['revision'], proposal_id=plan['id'], decision='accepted'), _body_review=identity)
        else:
            engine.act(project, action['action'], values)
    before, after = deviation_report(state), deviation_report(sandbox.state)
    return sandbox.state, dict(before=before, after=after,
        reason_delta={reason: after['deviations_by_reason'][reason] - before['deviations_by_reason'][reason]
                      for reason in ('late', 'early', 'unplanned', 'missing', 'blocked')})


def prepare_f1(state, actions, identity):
    """Save F1 proposals before their later decision, preserving its history rule."""
    from novel_writer.application.knowledge import command
    sandbox = PlanningSandbox(state)
    service = SimpleNamespace(repository=sandbox, get=sandbox.get)
    project = state['document']['project']['id']
    for index, action in enumerate(actions):
        if action['action'] == 'prepare_plan':
            command(service, project, 'prepare_plan', dict(action['values'],
                operation_id=str(uuid5(NAMESPACE_URL, identity + '/change/' + str(index))),
                expected_revision=state['revision']))
    return sandbox.state


def reject_f1(state, actions, identity, linked_plans=()):
    from novel_writer.application.knowledge import command
    sandbox = PlanningSandbox(state)
    service = SimpleNamespace(repository=sandbox, get=sandbox.get)
    for index, action in enumerate(actions):
        if action['action'] == 'prepare_plan':
            command(service, state['document']['project']['id'], 'decide_plan',
                    dict(operation_id=str(uuid5(NAMESPACE_URL, identity + '/reject/' + str(index))),
                         expected_revision=state['revision'], proposal_id=linked_plans[0] if linked_plans else str(uuid5(NAMESPACE_URL, identity + '/change/' + str(index))),
                         decision='rejected'), _body_review=identity)
    return sandbox.state
