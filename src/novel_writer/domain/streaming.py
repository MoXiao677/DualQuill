"""Detect explicit streaming destination snapshots without rewriting old inputs."""
def contains(value):
    if isinstance(value,dict):
        return value.get('stream_mode')=='sse' or any(contains(v) for v in value.values())
    if isinstance(value,(list,tuple)):return any(contains(v) for v in value)
    return False

def upgrade(state):
    if contains(state):
        from novel_writer.application.chapter_lifecycle import upgrade as prior
        prior(state);state['workspace_version']=max(state['workspace_version'],33)
