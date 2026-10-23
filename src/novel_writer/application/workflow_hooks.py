"""可信业务组合守卫，不接受HTTP/模板中的回调。"""
def owned_task(state,task_id):return any(a['task_id']==task_id for a in state.get('workflow_attempts',[]))
def owned_artifact(state,kind,identifier):return any(any(r['kind']==kind and r['entity_id']==identifier for r in e['output_refs']) for e in state.get('workflow_node_events',[]))
