"""Version only explicit dedicated semantic-summary frozen requests."""
def contains(value):
    if isinstance(value,dict):return value.get('prompt_version')=='chapter-summary-json-1' or any(contains(v) for v in value.values())
    if isinstance(value,(list,tuple)):return any(contains(v) for v in value)
    return False

def upgrade(state):
    if contains(state):
        from novel_writer.application.chapter_lifecycle import upgrade as prior
        prior(state);state['workspace_version']=max(state['workspace_version'],34)
