"""Upgrade only explicit new writes; never rewrite old frozen records on read."""
def upgrade(state):
 from novel_writer.application.chapter_lifecycle import upgrade as previous
 from novel_writer.domain.sampling import contains_native
 previous(state);state['workspace_version']=max(state['workspace_version'],29 if contains_native(state) else 28)
